# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: Response 배치 실행
# * 작성일: 2026-11-24
# * 설명: 기사 단위 OpenAI Batch 및 OpenAI 호환 병렬 호출
# ***************************************************
import hashlib
import json
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack, closing
from pathlib import Path
from uuid import uuid4

from jsonschema import Draft202012Validator, ValidationError
from openai import APIConnectionError, APIStatusError, NotFoundError

from . import result as review_result
from .prompt import build_system_prompt
from .response import PROMPT_DIR, create_client, prepare_document, response_request
from .response_input import load_response_documents
from .response_state import ResponseState, atomic_path, now, run_metadata
from .schema import RESPONSE_SCHEMA

ENDPOINT = "/v1/responses"
MAX_FILE_BYTES = 200_000_000
VALIDATOR = Draft202012Validator(RESPONSE_SCHEMA)


def _error(exc):
    status = getattr(exc, "status_code", None)
    message = str(exc)
    for name in ("OPENAI_API_KEY", "OPENROUTER_API_KEY"):
        secret = os.getenv(name)
        if secret:
            message = message.replace(secret, "[redacted]")
    return {"type": type(exc).__name__, "message": message[:2000], "status_code": status}


def _retryable(exc):
    status = getattr(exc, "status_code", None)
    return (isinstance(exc, (APIConnectionError, TimeoutError, ConnectionError))
            or status in (408, 409, 429) or (status is not None and 500 <= status < 600))


def _failed(context, error, attempts=1):
    result = review_result.build_fallback_result(context["sentences"])
    return context["doc_id"], attempts, result, error


def _parse(body, context, attempts):
    try:
        if body.get("status") != "completed" or body.get("error"):
            raise ValueError(f"Responses status={body.get('status')}: "
                             f"{body.get('error') or body.get('incomplete_details')}")
        parts = []
        for item in body["output"]:
            if item["type"] == "message":
                for content in item["content"]:
                    if content["type"] == "refusal":
                        raise ValueError("Responses output contains a refusal")
                    if content["type"] == "output_text":
                        parts.append(content["text"])
        data = json.loads("".join(parts))
        VALIDATOR.validate(data)
        result = review_result.build_result(data, context["sentences"])
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        return _failed(context, _error(exc), attempts)
    except ValidationError as exc:
        return _failed(context, {"type": "ValidationError", "message": exc.message[:2000]}, attempts)
    return context["doc_id"], attempts, result, None


def _sync_request(client, task, max_retries, backoff, max_backoff):
    for attempt in range(1, max_retries + 2):
        try:
            response = client.responses.create(**task["request"]["body"])
        except Exception as exc:
            if attempt > max_retries or not _retryable(exc):
                return _failed(task["context"], _error(exc), attempt)
            time.sleep(min(max_backoff, backoff * 2 ** (attempt - 1)))
            continue
        return _parse(response.model_dump(), task["context"], attempt)


def _sync_outcomes(client, tasks, workers, max_retries, backoff, max_backoff):
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_sync_request, client, task, max_retries, backoff, max_backoff)
                   for task in tasks}
        try:
            for future in as_completed(futures):
                futures.remove(future)
                yield future.result()
        except KeyboardInterrupt:
            for future in futures:
                future.cancel()
            for future in futures:
                if not future.cancelled():
                    yield future.result()
            raise


def _prepare(doc_ids, documents, version, press, model, prompt):
    by_id = {doc["id"]: doc for doc in documents}
    for key in doc_ids:
        context = {"doc_id": key, "sentences": []}
        try:
            article, instructions, sentences = prepare_document(by_id[key], prompt)
            context["sentences"] = sentences
            if not any((s.get("decision") or {}).get("review_candidate") is True for s in sentences):
                raise ValueError("대상 기사에 review_candidate 문장이 없습니다")
            identity = json.dumps([version, press, key], ensure_ascii=False).encode()
            custom_id = hashlib.sha256(identity).hexdigest()
            request = dict(custom_id=custom_id, method="POST", url=ENDPOINT,
                           body=response_request(model, instructions, article))
        except (KeyError, TypeError, ValueError) as exc:
            yield None, _failed(context, _error(exc), 0)
            continue
        yield {"request": request, "context": context}, None


def _batch_groups(tasks):
    group, size = [], 0
    for task in tasks:
        line = (json.dumps(task["request"], ensure_ascii=False, separators=(",", ":")) + "\n").encode()
        if len(line) > MAX_FILE_BYTES:
            yield [], [_failed(task["context"], _error(ValueError("단일 요청이 Batch 파일 한도를 초과합니다")), 0)]
            continue
        if size + len(line) > MAX_FILE_BYTES:
            yield group, []
            group, size = [], 0
        group.append((task, line))
        size += len(line)
    if group:
        yield group, []


def _collect_batch(client, state, job, batch):
    contexts = job["contexts"]
    outcomes = {}
    for kind in ("output", "error"):
        file_id = getattr(batch, f"{kind}_file_id")
        if not file_id:
            continue
        path = state.directory / "batches" / job["token"] / f"{kind}.jsonl"
        if not path.exists():
            try:
                with (atomic_path(path) as temp,
                      client.files.with_streaming_response.content(file_id) as stream):
                    stream.stream_to_file(temp)
            except NotFoundError as exc:
                state.log("batch_file_missing", file_id=file_id, error=_error(exc))
                continue
        with path.open(encoding="utf-8") as source:
            for line_number, line in enumerate(source, 1):
                try:
                    row = json.loads(line)
                    key = row["custom_id"]
                    if key not in contexts:
                        raise ValueError("unknown custom_id")
                except (ValueError, KeyError, TypeError) as exc:
                    state.log("batch_output_invalid", file_id=file_id, line=line_number, error=_error(exc))
                    continue
                context = contexts[key]
                response = row.get("response")
                if key in outcomes:
                    outcomes[key] = _failed(context, _error(ValueError(f"duplicate custom_id: {key}")))
                elif row.get("error") or not isinstance(response, dict):
                    outcomes[key] = _failed(context, {"type": "BatchRequestError",
                        "message": str(row.get("error") or "Missing response object")})
                elif response.get("status_code") != 200:
                    outcomes[key] = _failed(context, {"type": "BatchRequestError",
                        "message": str(response.get("body")), "status_code": response.get("status_code")})
                else:
                    outcomes[key] = _parse(response.get("body"), context, 1)
    missing = {"type": "MissingBatchResult", "message": f"Batch {batch.id}: {batch.status}, "
               f"errors={batch.errors}"}
    for key in contexts.keys() - outcomes.keys():
        outcomes[key] = _failed(contexts[key], missing)
    return list(outcomes.values())


def _finish_remote(client, state, job, poll_seconds, *, resume):
    """서버 제출과 로컬 커밋 사이에 중단된 경우 업로드 ID로 기존 Batch를 찾는다."""
    if not job.get("batch_id"):
        batch = None
        if resume:
            batch = next((item for item in client.batches.list(limit=100)
                          if item.input_file_id == job["input_file_id"]), None)
        if batch is None:
            # 접수 직후 연결이 끊기면 다음 실행에서 조회한다. SDK의 자동 POST 재시도는 끈다.
            batch = client.with_options(max_retries=0).batches.create(
                input_file_id=job["input_file_id"], endpoint=ENDPOINT,
                completion_window="24h", metadata={"run_token": job["token"]})
        job["batch_id"] = batch.id
        state.set_job(job)
        state.log("batch_submitted", batch_id=batch.id, count=len(job["contexts"]))
    while True:
        batch = client.batches.retrieve(job["batch_id"])
        state.log("batch_poll", batch_id=batch.id, status=batch.status)
        if batch.status in {"completed", "failed", "expired", "cancelled"}:
            break
        time.sleep(poll_seconds)
    outcomes = _collect_batch(client, state, job, batch)
    event = "batch_completed" if batch.status == "completed" else "batch_failed"
    state.log(event, batch_id=batch.id, status=batch.status)
    return outcomes


def _remote(client, state, group, poll_seconds, job=None):
    resume = job is not None
    if not resume:
        token = uuid4().hex
        path = state.directory / "batches" / token / "input.jsonl"
        path.parent.mkdir(parents=True)
        contexts = {}
        with path.open("wb") as out:
            for task, line in group:
                out.write(line)
                contexts[task["request"]["custom_id"]] = task["context"]
            out.flush()
        job = {"token": token, "contexts": contexts}
    try:
        if not resume:
            with path.open("rb") as data:
                job["input_file_id"] = client.files.create(file=data, purpose="batch").id
            state.set_job(job)
        outcomes = _finish_remote(client, state, job, poll_seconds, resume=resume)
    except APIStatusError as exc:
        # 조회 권한/일시 장애 시 이미 접수된 작업을 다시 제출하지 않는다.
        if _retryable(exc) or (job.get("batch_id") and exc.status_code != 404):
            raise
        outcomes = [_failed(ctx, _error(exc)) for ctx in job["contexts"].values()]
        state.log("batch_failed", batch_id=job.get("batch_id"), error=_error(exc))
    state.save(outcomes, finish_job=True)


def run_response_batch(doc_ids, output_root, *, press, data_version, provider, model,
                       mode="batch", batch_size=20, max_workers=4, max_retries=3,
                       timeout=120, backoff=2, max_backoff=60, poll_seconds=30, force=False,
                       load_documents=load_response_documents, client=None, system_prompt=None):
    """한 언론사의 기사 ID를 실행한다. 같은 출력 루트와 설정으로 재개할 수 있다."""
    provider, mode = provider.upper(), mode.lower()
    if provider not in {"OPENAI", "OPENROUTER"} or mode not in {"batch", "parallel", "sync"}:
        raise ValueError("provider는 OPENAI/OPENROUTER, mode는 batch/parallel/sync 중에서 선택하세요")
    if not model or not 1 <= batch_size <= 50_000 or max_workers < 1 or max_retries < 0:
        raise ValueError("model, batch_size(1~50000), max_workers 또는 max_retries 설정 오류")
    if timeout <= 0 or min(backoff, max_backoff, poll_seconds) < 0:
        raise ValueError("timeout은 양수, 대기 시간은 0 이상이어야 합니다")
    effective = "parallel" if provider == "OPENROUTER" and mode == "batch" else mode
    root = Path(output_root)
    if not press or Path(press).name != press or press in {".", ".."}:
        raise ValueError(f"잘못된 언론사 폴더명: {press}")
    directory = root / "reports" / press
    directory.mkdir(parents=True, exist_ok=True)
    ids = list(dict.fromkeys(doc_ids))
    prompt = system_prompt if system_prompt is not None else build_system_prompt(PROMPT_DIR)
    hashes = dict(prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                  postprocess_sha256=review_result.POSTPROCESS_SHA256)
    meta = run_metadata(root, provider, model, data_version, os.getenv("PROMPT_VERSION"), hashes)
    info = dict(meta, press=press, mode=effective, requested_mode=mode, started_at=now(),
                selected=len(ids), skipped=0)
    with ExitStack() as stack:
        db = stack.enter_context(closing(sqlite3.connect(directory / "manifest.sqlite3", timeout=1)))
        state = ResponseState(db, directory, root.name, press)
        state.restore_exports()
        active = state.job()
        # 진행 중인 서버 작업의 결과는 원래 문서 스냅샷과 함께 먼저 회수한다.
        def open_client():
            return stack.enter_context(create_client(
                provider, timeout=timeout, max_retries=max_retries if effective == "batch" else 0))

        try:
            if active:
                if client is None:
                    client = open_client()
                _remote(client, state, None, poll_seconds, active)
            pending = state.select(ids, force)
            info["skipped"] = len(ids) - len(pending)
            if force:
                state.export_documents()
            state.summary(info, "running")
            state.log("run_started", mode=effective, selected=len(ids), skipped=info["skipped"],
                      force=force, **hashes)
            if pending and client is None:
                client = open_client()
            for start in range(0, len(pending), batch_size):
                keys = pending[start:start + batch_size]
                documents = load_documents(keys, data_version=data_version, press=press)
                tasks, invalid = [], []
                for task, failure in _prepare(keys, documents, data_version, press, model, prompt):
                    if failure:
                        invalid.append(failure)
                    else:
                        tasks.append(task)
                if invalid:
                    state.save(invalid)
                if effective == "batch":
                    for group, oversized in _batch_groups(tasks):
                        if oversized:
                            state.save(oversized)
                        else:
                            _remote(client, state, group, poll_seconds)
                        state.summary(info, "running")
                elif tasks:
                    workers = 1 if effective == "sync" else max_workers
                    state.log("batch_submitted", count=len(tasks), workers=workers)
                    outcomes = _sync_outcomes(client, tasks, workers, max_retries, backoff, max_backoff)
                    state.save(outcomes, checkpoint_each=True)
                    state.log("batch_completed", count=len(tasks))
                state.summary(info, "running")
            state.export_parquet()
        except (Exception, KeyboardInterrupt) as exc:
            if isinstance(exc, KeyboardInterrupt):
                state.restore_exports()
            state.log("run_interrupted", error=_error(exc))
            state.summary(info, "interrupted", finished=True)
            raise
        return state.summary(info, "completed", finished=True)
