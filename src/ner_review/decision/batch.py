# -*- coding: utf-8 -*-
"""PostgreSQL 기반 Decision API 배치 검수 실행기.

기존 ``decision.py``의 파일 기반 실험 코드는 유지하고, 실제 배치 실행에
필요한 최소 기능(스트리밍 추출, 재개, 재시도, 원자적 JSONL 저장)을 이
모듈에 모아 둔다. 이 모듈은 import만으로 API를 호출하지 않는다.
"""

from __future__ import annotations

import json
import math
import os
import random
import re
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

import psycopg
from psycopg.rows import dict_row

from src.config import get_postgre_connect

from .decision import DECISION_MODEL
from .prompt import build_batch_decision_questions, build_batch_decision_system_prompt


SCHEMA_VERSION = "ner-decision-v2"
PROMPT_VERSION = "decision-v2"
SUPPORTED_DECISION_MODEL = "gpt-6-luna"
DEFAULT_BATCH_SIZE = 20
DEFAULT_MAX_WORKERS = 4
DEFAULT_MAX_RETRIES = 5
DEFAULT_BACKOFF_SECONDS = 2.0
DEFAULT_REQUEST_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_INPUT_CHARS = 120_000
_TRUE_VALUES = {"true", "1", "t", "yes", "y"}
_FALSE_VALUES = {"false", "0", "f", "no", "n", ""}
_ENTITY_TAG_PATTERN = re.compile(r"<([^<>:]+):\s*(PS|LC|OG|AF|EV|DT)>")


class DecisionCallError(RuntimeError):
    """최종 실패 시 시도 횟수와 재시도 가능 여부를 보존한다."""

    def __init__(self, message: str, *, attempts: int, retryable: bool, cause: Exception):
        super().__init__(message)
        self.attempts = attempts
        self.retryable = retryable
        self.cause_type = type(cause).__name__


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=_json_default)


def _is_true(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in _TRUE_VALUES


def _none_if_nan(value: Any) -> Any:
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
    except TypeError:
        pass
    return value


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    if hasattr(value, "__dict__"):
        return vars(value)
    return {}


def _answer_dict(answer: Any) -> dict[str, Any]:
    raw = _as_dict(answer)
    if not raw and isinstance(answer, str):
        raw = {"value": answer}
    return {
        "name": getattr(answer, "name", None) or raw.get("name"),
        "type": getattr(answer, "type", None) or raw.get("type"),
        "choice": getattr(answer, "choice", None) if getattr(answer, "choice", None) is not None else raw.get("choice"),
        "value": getattr(answer, "value", None) if getattr(answer, "value", None) is not None else raw.get("value"),
        "text": getattr(answer, "text", None) if getattr(answer, "text", None) is not None else raw.get("text"),
        "confidence": getattr(answer, "confidence", None) if getattr(answer, "confidence", None) is not None else raw.get("confidence"),
        "probabilities": getattr(answer, "probabilities", None) if getattr(answer, "probabilities", None) is not None else raw.get("probabilities"),
        "raw": json.loads(json.dumps(raw, ensure_ascii=False, default=_json_default)),
    }


def _answer_value(answer: dict[str, Any]) -> Any:
    value = answer.get("choice")
    if value is None:
        value = answer.get("value")
    if value is None:
        value = answer.get("text")
    return value


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _TRUE_VALUES or lowered in {"error", "wrong", "needed", "merge"}:
            return True
        if lowered in _FALSE_VALUES or lowered in {"normal", "none", "not_needed", "no_merge"}:
            return False
    return None


def _tag_error_choice(value: Any) -> tuple[bool, str | None]:
    """태그오류 choice를 결과용 Boolean과 세부 유형으로 변환한다."""
    if value == "wrong_major_tag":
        return True, "wrong_major_tag"
    if value == "other_tagging_error":
        return True, "other_tagging_error"
    if value == "normal":
        return False, None
    boolean = _as_bool(value)
    if boolean is None:
        raise ValueError("tagging_error choice가 지원 형식이 아님")
    return boolean, "other_tagging_error" if boolean else None


def _candidate_rule_ids(target: dict[str, Any]) -> list[str]:
    rule_ids = {
        item.get("rule_id")
        for item in target.get("sentence_rule_evidence", [])
        if item.get("rule_id")
    }
    for entity in target.get("entities", []):
        rule_ids.update(
            item.get("rule_id")
            for item in entity.get("rule_evidence", [])
            if item.get("rule_id")
        )
    return sorted(rule_ids)


def _answer_probabilities(answer: dict[str, Any]) -> Any:
    return (answer.get("raw") or {}).get("probabilities") or answer.get("probabilities")


def _extract_usage(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage", None)
    raw = _as_dict(usage)
    return {
        "input_tokens": raw.get("input_tokens", raw.get("prompt_tokens")),
        "output_tokens": raw.get("output_tokens", raw.get("completion_tokens")),
        "total_tokens": raw.get("total_tokens"),
    }


def _is_retryable(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status is not None:
        return int(status) == 408 or int(status) == 409 or int(status) == 429 or int(status) >= 500
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    return any(token in name or token in message for token in ("timeout", "rate", "connection", "tempor", "overloaded", "429"))


def _retry_delay(attempt: int, backoff_seconds: float, max_backoff_seconds: float) -> float:
    base = min(max_backoff_seconds, backoff_seconds * (2 ** max(0, attempt - 1)))
    return base * (0.8 + random.random() * 0.4)


def _active_rule_evidence(row: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = []
    for key, value in row.items():
        if not key.startswith("EXT_") or key.endswith("_PATTERN") or not _is_true(value):
            continue
        evidence.append({
            "rule_id": key,
            "pattern": _none_if_nan(row.get(f"{key}_PATTERN")),
        })
    return evidence


def _entity_from_rule_row(row: dict[str, Any]) -> dict[str, Any] | None:
    entity_id = _none_if_nan(row.get("rule_entity_id"))
    if entity_id is None:
        return None
    span = _none_if_nan(row.get("entity_tagging"))
    entity_type = _none_if_nan(row.get("entity_type"))
    if not span:
        span = _none_if_nan(row.get("entity_name"))
    return {
        "entity_id": str(entity_id),
        "target_span": span or "",
        "target_type": entity_type or "",
        "rule_evidence": _active_rule_evidence(row),
    }


def _merge_entity(entities: dict[str, dict[str, Any]], entity: dict[str, Any]) -> None:
    current = entities.setdefault(entity["entity_id"], entity)
    for key in ("target_span", "target_type"):
        if not current.get(key) and entity.get(key):
            current[key] = entity[key]
    seen = {(item.get("rule_id"), item.get("pattern")) for item in current["rule_evidence"]}
    for item in entity.get("rule_evidence", []):
        if (item.get("rule_id"), item.get("pattern")) not in seen:
            current["rule_evidence"].append(item)


def _target_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    first = rows[0]
    entities: dict[str, dict[str, Any]] = {}
    sentence_rules: dict[tuple[Any, Any], dict[str, Any]] = {}
    for row in rows:
        entity = _entity_from_rule_row(row)
        if entity:
            _merge_entity(entities, entity)
        for item in _active_rule_evidence(row):
            key = (item["rule_id"], item.get("pattern"))
            sentence_rules[key] = item

    original_form = _none_if_nan(first.get("review_original_form")) or _none_if_nan(first.get("rule_form")) or ""
    if not entities:
        for index, match in enumerate(_ENTITY_TAG_PATTERN.finditer(original_form), start=1):
            sentence_id = first["review_sentence_id"]
            entities[f"{sentence_id}.E{index}"] = {
                "entity_id": f"{sentence_id}.E{index}",
                "target_span": match.group(0),
                "target_type": match.group(2),
                "rule_evidence": [],
            }

    return {
        "data_version": first["review_data_version"],
        "press": first["review_press"],
        "doc_id": first["review_doc_id"],
        "sentence_id": first["review_sentence_id"],
        "original_form": original_form,
        "entities": list(entities.values()),
        "sentence_rule_evidence": list(sentence_rules.values()),
    }


def stream_review_targets(
    connection_factory: Callable[[], Any] = get_postgre_connect,
    *,
    data_version: str | None = None,
    press: str | None = None,
    fetch_size: int = 200,
) -> Iterator[dict[str, Any]]:
    """LLM검수 대상과 활성 룰 결과를 정렬된 문장 단위로 스트리밍한다."""
    conditions = ["h.review_method = 'LLM검수'"]
    params: list[Any] = []
    if data_version:
        conditions.append("h.data_version = %s")
        params.append(data_version)
    if press:
        conditions.append("h.press = %s")
        params.append(press)
    query = f"""
        SELECT
            h.data_version AS review_data_version,
            h.press AS review_press,
            h.doc_id AS review_doc_id,
            h.sentence_id AS review_sentence_id,
            h.original_form AS review_original_form,
            r.entity_id AS rule_entity_id,
            r.form AS rule_form,
            r.entity_tagging, r.entity_name, r.entity_type,
            r.*
        FROM ner_human_review AS h
        LEFT JOIN ner_rule_results_3 AS r
          ON r.data_version = h.data_version
         AND r.doc_id = h.doc_id
         AND r.sentence_id = h.sentence_id
        WHERE {' AND '.join(conditions)}
        ORDER BY h.press, h.data_version, h.doc_id, h.sentence_id, r.entity_id NULLS FIRST
    """
    with connection_factory() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query, params)
            current_key = None
            current_rows: list[dict[str, Any]] = []
            while True:
                chunk = cursor.fetchmany(fetch_size)
                if not chunk:
                    break
                for row in chunk:
                    key = (row["review_data_version"], row["review_press"], row["review_doc_id"], row["review_sentence_id"])
                    if current_key is not None and key != current_key:
                        yield _target_from_rows(current_rows)
                        current_rows = []
                    current_key = key
                    current_rows.append(row)
            if current_rows:
                yield _target_from_rows(current_rows)


def build_decision_input(target: dict[str, Any], max_input_chars: int = DEFAULT_MAX_INPUT_CHARS) -> str:
    """Decision API user 입력을 만든다. 원문/기존 태깅/활성 룰을 함께 제공한다."""
    payload = {
        "data_version": target["data_version"],
        "press": target["press"],
        "doc_id": target["doc_id"],
        "sentence_id": target["sentence_id"],
        "sentence": target["original_form"],
        "existing_entities": target.get("entities", []),
        "active_rule_evidence": target.get("sentence_rule_evidence", []),
    }
    text = "# DECISION_REVIEW_TARGET\n" + _json_dumps(payload)
    if len(text) <= max_input_chars:
        return text
    # 너무 긴 문장은 원문과 태깅을 우선 보존하고 룰 패턴만 줄인다.
    payload["active_rule_evidence"] = [
        {"rule_id": item.get("rule_id")} for item in payload["active_rule_evidence"]
    ]
    text = "# DECISION_REVIEW_TARGET\n" + _json_dumps(payload)
    if len(text) > max_input_chars:
        raise ValueError(f"input_too_large: {len(text)} chars > {max_input_chars}")
    return text


def _find_answer(answers: list[dict[str, Any]], suffix: str) -> dict[str, Any]:
    for answer in answers:
        if str(answer.get("name", "")).endswith(suffix):
            return answer
    raise ValueError(f"필수 Decision answer 누락: {suffix}")


def _normalise_result(target: dict[str, Any], response: Any, *, run_id: str, model: str, attempts: int, input_chars: int) -> dict[str, Any]:
    raw_answers = getattr(response, "answers", None)
    if raw_answers is None and isinstance(response, dict):
        raw_answers = response.get("answers")
    answers = [_answer_dict(answer) for answer in (raw_answers or [])]
    error_answer = _find_answer(answers, "__tagging_error")
    merge_answer = _find_answer(answers, "__tagging_merge")
    error_choice, error_type = _tag_error_choice(_answer_value(error_answer))
    merge_choice = _as_bool(_answer_value(merge_answer))
    if merge_choice is None:
        raise ValueError("tagging_merge choice가 Boolean으로 해석되지 않음")
    response_id = getattr(response, "id", None) or _as_dict(response).get("id")
    usage = _extract_usage(response)
    candidate_rule_ids = _candidate_rule_ids(target)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "completed",
        "run_id": run_id,
        "executed_at": utc_now(),
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "data_version": target["data_version"],
        "press": target["press"],
        "doc_id": target["doc_id"],
        "sentence_id": target["sentence_id"],
        "original_form": target["original_form"],
        "tagging_error": {
            "is_error": error_choice,
            "error_type": error_type,
            "target_entity_id": None,
            "target_span": None,
            "corrected_span": None,
            "candidate_rule_ids": candidate_rule_ids,
            "reason": "Decision API choice 결과: 정상" if not error_choice else (
                "Decision API choice 결과: 대분류 태그 오류 후보"
                if error_type == "wrong_major_tag"
                else "Decision API choice 결과: 기타 태그 오류 후보"
            ),
            "confidence": error_answer.get("confidence"),
            "probabilities": _answer_probabilities(error_answer),
        },
        "tagging_merge": {
            "needed": merge_choice,
            "merge_entity_ids": [],
            "merge_target": None,
            "corrected_tagging": None,
            "candidate_rule_ids": candidate_rule_ids,
            "reason": "Decision API choice 결과만 제공됨: 병합 불필요" if not merge_choice else "Decision API choice 결과만 제공됨: 병합 후보",
            "confidence": merge_answer.get("confidence"),
            "probabilities": _answer_probabilities(merge_answer),
        },
        "source": {
            "existing_entities": target.get("entities", []),
            "active_rule_evidence": target.get("sentence_rule_evidence", []),
        },
        "api": {
            "response_id": response_id,
            "attempts": attempts,
            "input_chars": input_chars,
            "usage": usage,
            "answers": answers,
            "detail_generation_supported": False,
        },
    }


def _write_jsonl_atomic(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    count = 0
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as output:
            for row in rows:
                output.write(_json_dumps(row) + "\n")
                count += 1
            output.flush()
            os.fsync(output.fileno())
        for replace_attempt in range(5):
            try:
                os.replace(temp_path, path)
                break
            except PermissionError:
                if replace_attempt == 4:
                    raise
                time.sleep(0.2 * (replace_attempt + 1))
        return count
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _append_jsonl_atomic(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    """기존 내용과 새 배치를 임시 파일에 합친 뒤 원자적으로 교체한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    count = 0
    try:
        with temp_path.open("wb") as output:
            if path.is_file():
                with path.open("rb") as previous:
                    shutil.copyfileobj(previous, output)
            for row in rows:
                output.write((_json_dumps(row) + "\n").encode("utf-8"))
                count += 1
            output.flush()
            os.fsync(output.fileno())
        for replace_attempt in range(5):
            try:
                os.replace(temp_path, path)
                break
            except PermissionError:
                if replace_attempt == 4:
                    raise
                time.sleep(0.2 * (replace_attempt + 1))
        return count
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _read_keys(path: Path) -> set[tuple[str, str, str, str]]:
    if not path.is_file():
        return set()
    keys: set[tuple[str, str, str, str]] = set()
    with path.open(encoding="utf-8") as source:
        for line in source:
            try:
                row = json.loads(line)
                if row.get("status") == "completed":
                    keys.add(tuple(str(row[field]) for field in ("data_version", "press", "doc_id", "sentence_id")))
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
    return keys


def _press_dir(output_root: Path, press: str) -> Path:
    return output_root / "press" / press


def _safe_press_name(press: str) -> str:
    return re.sub(r"[<>:\"/\\|?*]", "_", str(press))


def _call_with_retry(
    target: dict[str, Any],
    *,
    client: Any,
    model: str,
    max_retries: int,
    backoff_seconds: float,
    max_backoff_seconds: float,
    request_timeout_seconds: float | None,
    max_input_chars: int,
    run_id: str,
) -> tuple[dict[str, Any], int]:
    input_text = build_decision_input(target, max_input_chars=max_input_chars)
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 2):
        try:
            request = {
                "model": model,
                "input": [
                    {"role": "developer", "content": [{"type": "input_text", "text": build_batch_decision_system_prompt()}]},
                    {"role": "user", "content": [{"type": "input_text", "text": input_text}]},
                ],
                "questions": build_batch_decision_questions(target["sentence_id"]),
            }
            # 현재 프로젝트의 Decisions API는 timeout을 client 생성 시 받으므로
            # 호환성을 위해 request에는 넣지 않는다.
            response = client.decisions.create(**request)
            return _normalise_result(target, response, run_id=run_id, model=model, attempts=attempt, input_chars=len(input_text)), attempt
        except Exception as exc:
            last_exc = exc
            retryable = _is_retryable(exc)
            if attempt > max_retries or not retryable:
                raise DecisionCallError(
                    str(exc), attempts=attempt, retryable=retryable, cause=exc
                ) from exc
            time.sleep(_retry_delay(attempt, backoff_seconds, max_backoff_seconds))
    raise last_exc or RuntimeError("Decision API 호출 실패")


def _failure_row(target: dict[str, Any], *, run_id: str, model: str, status: str, error: Exception, attempts: int = 0, retryable: bool = False) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "run_id": run_id,
        "executed_at": utc_now(),
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "data_version": target["data_version"],
        "press": target["press"],
        "doc_id": target["doc_id"],
        "sentence_id": target["sentence_id"],
        "original_form": target.get("original_form", ""),
        "error": {
            "type": getattr(error, "cause_type", type(error).__name__),
            "message": str(error),
            "attempts": attempts,
            "retryable_after_failure": retryable,
        },
    }


@contextmanager
def _client_context(client: Any | None, timeout_seconds: float | None):
    if client is not None:
        yield client
        return
    from openai import OpenAI

    kwargs = {}
    if timeout_seconds is not None:
        kwargs["timeout"] = timeout_seconds
    yield OpenAI(**kwargs)


def _write_summary(path: Path, summary: dict[str, Any]) -> None:
    _write_jsonl_atomic(path, [summary])


def run_press(
    press: str,
    output_root: str | Path,
    *,
    data_version: str | None = None,
    connection_factory: Callable[[], Any] = get_postgre_connect,
    client: Any | None = None,
    model: str = DECISION_MODEL,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_workers: int = DEFAULT_MAX_WORKERS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    max_backoff_seconds: float = 60.0,
    request_timeout_seconds: float | None = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    max_input_chars: int = DEFAULT_MAX_INPUT_CHARS,
    run_id: str | None = None,
    limit: int | None = None,
    force: bool = False,
    progress: Callable[[dict[str, Any]], None] | None = print,
) -> dict[str, Any]:
    """한 언론사를 배치 처리한다. 완료 JSONL은 재실행 시 건너뛴다."""
    if batch_size <= 0 or max_workers <= 0 or max_retries < 0 or (limit is not None and limit <= 0):
        raise ValueError("batch_size/max_workers는 1 이상, max_retries는 0 이상이어야 합니다.")
    if model != SUPPORTED_DECISION_MODEL:
        raise ValueError(f"현재 Decisions API 지원 모델은 {SUPPORTED_DECISION_MODEL}입니다: {model}")
    root = Path(output_root)
    run_id = run_id or root.name
    directory = _press_dir(root, _safe_press_name(press))
    result_path = directory / "results.jsonl"
    failure_path = directory / "failures.jsonl"
    log_path = directory / "execution.log.jsonl"
    if force:
        completed = set()
    else:
        completed = _read_keys(result_path)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "press": press,
        "data_version": data_version,
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "started_at": utc_now(),
        "status": "running",
        "batch_size": batch_size,
        "max_workers": max_workers,
        "max_retries": max_retries,
        "completed": len(completed),
        "failed": 0,
        "skipped": 0,
        "pending": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "request_count": 0,
        "retried_requests": 0,
        "retry_targets": 0,
        "unprocessed": 0,
    }
    _write_summary(directory / "summary.json", summary)
    lock = threading.Lock()

    def report(event: dict[str, Any]) -> None:
        with lock:
            _append_jsonl_atomic(log_path, [{"at": utc_now(), **event}])
        if progress:
            progress(event)

    with _client_context(client, request_timeout_seconds) as api_client:
        targets = stream_review_targets(connection_factory, data_version=data_version, press=press)
        pending_batch: list[dict[str, Any]] = []
        selected_count = 0
        for target in targets:
            key = tuple(str(target[field]) for field in ("data_version", "press", "doc_id", "sentence_id"))
            if key in completed:
                summary["skipped"] += 1
                continue
            pending_batch.append(target)
            selected_count += 1
            if len(pending_batch) < batch_size:
                if limit is not None and selected_count >= limit:
                    break
                continue
            _run_batch(pending_batch, summary, directory, api_client, model, run_id, max_workers, max_retries, backoff_seconds, max_backoff_seconds, request_timeout_seconds, max_input_chars, report)
            pending_batch = []
            _write_summary(directory / "summary.json", summary)
            if limit is not None and selected_count >= limit:
                break
        if pending_batch:
            _run_batch(pending_batch, summary, directory, api_client, model, run_id, max_workers, max_retries, backoff_seconds, max_backoff_seconds, request_timeout_seconds, max_input_chars, report)
            _write_summary(directory / "summary.json", summary)
    summary["pending"] = max(0, summary["pending"])
    summary["status"] = "completed" if summary["failed"] == 0 else "completed_with_failures"
    summary["finished_at"] = utc_now()
    _write_summary(directory / "summary.json", summary)
    return summary


def _run_batch(
    batch: list[dict[str, Any]], summary: dict[str, Any], directory: Path, client: Any, model: str, run_id: str,
    max_workers: int, max_retries: int, backoff_seconds: float, max_backoff_seconds: float,
    request_timeout_seconds: float | None, max_input_chars: int, report: Callable[[dict[str, Any]], None],
) -> None:
    completed_rows: list[dict[str, Any]] = []
    failure_rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _call_with_retry, target, client=client, model=model, max_retries=max_retries,
                backoff_seconds=backoff_seconds, max_backoff_seconds=max_backoff_seconds,
                request_timeout_seconds=request_timeout_seconds, max_input_chars=max_input_chars, run_id=run_id,
            ): target for target in batch
        }
        for future in as_completed(futures):
            target = futures[future]
            try:
                row, attempts = future.result()
                completed_rows.append(row)
                summary["completed"] += 1
                summary["request_count"] += attempts
                if attempts > 1:
                    summary["retried_requests"] += 1
                usage = row["api"]["usage"]
                summary["input_tokens"] += usage.get("input_tokens") or 0
                summary["output_tokens"] += usage.get("output_tokens") or 0
                report({"event": "completed", "press": target["press"], "doc_id": target["doc_id"], "sentence_id": target["sentence_id"], "attempts": attempts})
            except Exception as exc:
                status = "parse_error" if "answer" in str(exc).lower() or "boolean" in str(exc).lower() else "request_failed"
                attempts = getattr(exc, "attempts", 1)
                retryable = bool(getattr(exc, "retryable", False))
                failure_rows.append(_failure_row(target, run_id=run_id, model=model, status=status, error=exc, attempts=attempts, retryable=retryable))
                summary["failed"] += 1
                summary["request_count"] += attempts
                if attempts > 1:
                    summary["retried_requests"] += 1
                if retryable:
                    summary["retry_targets"] += 1
                summary["unprocessed"] += 1
                report({"event": status, "press": target["press"], "doc_id": target["doc_id"], "sentence_id": target["sentence_id"], "error": str(exc)})
    completed_rows.sort(key=lambda row: (str(row["doc_id"]), str(row["sentence_id"])))
    failure_rows.sort(key=lambda row: (str(row["doc_id"]), str(row["sentence_id"])))
    _append_jsonl_atomic(directory / "results.jsonl", completed_rows)
    _append_jsonl_atomic(directory / "failures.jsonl", failure_rows)
    report({"event": "batch_saved", "batch_size": len(batch), "completed": len(completed_rows), "failed": len(failure_rows)})


def estimate_usage(targets: Iterable[dict[str, Any]], sample_size: int = 100, chars_per_token: float = 4.0) -> dict[str, Any]:
    """샘플 입력 크기로 언론사별 대략적인 토큰량을 계산한다."""
    lengths = []
    for index, target in enumerate(targets):
        if index >= sample_size:
            break
        lengths.append(len(build_decision_input(target)))
    if not lengths:
        return {"sample_size": 0, "avg_input_chars": 0, "estimated_input_tokens": 0}
    average = sum(lengths) / len(lengths)
    return {
        "sample_size": len(lengths),
        "avg_input_chars": round(average, 1),
        "max_input_chars": max(lengths),
        "estimated_input_tokens": round(average / chars_per_token),
    }


def run_press_list(presses: Iterable[str], output_root: str | Path, **kwargs: Any) -> list[dict[str, Any]]:
    """언론사별 순차 실행. 각 언론사의 상태 파일은 독립적으로 저장한다."""
    return [run_press(press, output_root, **kwargs) for press in presses]


def _read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    with path.open(encoding="utf-8") as source:
        for line in source:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def count_completed_results(output_root: str | Path, press: str) -> int:
    """재시도 후 실제 완료 결과 수를 확인한다."""
    path = _press_dir(Path(output_root), _safe_press_name(press)) / "results.jsonl"
    return sum(1 for row in _read_jsonl_rows(path) if row.get("status") == "completed")


def run_press_with_remediation(
    press: str,
    output_root: str | Path,
    *,
    test_limit: int = 10,
    **kwargs: Any,
) -> dict[str, Any]:
    """소규모 테스트 실패 시 안전한 설정으로 한 번 자동 복구한다.

    재시도 대상은 rate limit/타임아웃/연결/5xx와 입력 크기 초과다.
    인증 오류, 모델 오류, 응답 형식 오류는 반복 호출하지 않는다.
    """
    limit = kwargs.pop("limit", test_limit)
    summary = run_press(press, output_root, limit=limit, **kwargs)
    directory = _press_dir(Path(output_root), _safe_press_name(press))
    failures = _read_jsonl_rows(directory / "failures.jsonl")
    if not failures:
        return summary

    remediable = []
    for row in failures:
        error = row.get("error") or {}
        message = str(error.get("message", "")).lower()
        if error.get("retryable_after_failure") or "input_too_large" in message:
            remediable.append(row)
    if not remediable:
        summary["remediation"] = "not_applied_non_retryable_failure"
        return summary

    retry_kwargs = dict(kwargs)
    retry_kwargs.update({
        "batch_size": 1,
        "max_workers": 1,
        "max_retries": max(int(kwargs.get("max_retries", DEFAULT_MAX_RETRIES)), 2),
        "backoff_seconds": max(float(kwargs.get("backoff_seconds", DEFAULT_BACKOFF_SECONDS)), 5.0),
        "max_backoff_seconds": max(float(kwargs.get("max_backoff_seconds", 60.0)), 120.0),
        "request_timeout_seconds": max(float(kwargs.get("request_timeout_seconds", DEFAULT_REQUEST_TIMEOUT_SECONDS)), 180.0),
        "max_input_chars": max(int(kwargs.get("max_input_chars", DEFAULT_MAX_INPUT_CHARS)), 256_000),
    })
    retry_summary = run_press(press, output_root, limit=limit, **retry_kwargs)
    retry_summary["remediation"] = "retryable_failures_retried_with_safe_settings"
    retry_summary["remediation_failure_count"] = len(remediable)
    retry_summary["completed_after_remediation"] = count_completed_results(output_root, press)
    return retry_summary


__all__ = [
    "SCHEMA_VERSION", "PROMPT_VERSION", "SUPPORTED_DECISION_MODEL", "stream_review_targets", "build_decision_input",
    "estimate_usage", "run_press", "run_press_list", "count_completed_results",
    "run_press_with_remediation",
]
