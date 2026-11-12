# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: decision.py
# * 작성일: 2026-11-12
# * 설명: Decisions API 호출 및 기사 단위 실행 파이프라인
# ***************************************************
import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
from openai import OpenAI
from langsmith import traceable
from langsmith.wrappers import wrap_openai

from .prompt import build_decision_questions, build_decision_system_prompt


DECISION_MODEL = "gpt-6-luna"
ENTITY_PATTERN = re.compile(r"<([^<>:]+):\s*(PS|LC|OG|AF|EV|DT)>")


@traceable(name="ner_decision", run_type="chain")
def call_decision(article_input, sentence_id, rule_ids, client=None, model=None):
    """입력 기사에 대해 선택한 Decisions 질문을 실행한다."""
    rule_ids = list(rule_ids)
    client = client or wrap_openai(OpenAI())
    decision = client.decisions.create(
        model=model or DECISION_MODEL,
        input=[
            {"role": "developer", "content": [{"type": "input_text", "text": build_decision_system_prompt(rule_ids)}]},
            {"role": "user", "content": [{"type": "input_text", "text": article_input}]},
        ],
        questions=build_decision_questions(sentence_id, rule_ids),
    )
    return decision.answers


def run_decision(article_input, sentence_id, client=None, model=None):
    """E001 결과에 따라 1차 또는 2차 Decisions 요청을 실행한다."""
    first_answers = call_decision(article_input, sentence_id, ["LLM_E001", "LLM_S001"], client, model)
    e001_answer = next(answer for answer in first_answers if answer.name == f"{sentence_id}__LLM_E001")
    if e001_answer.type == "refusal":
        raise RuntimeError("E001 Decisions answer was refused")
    if e001_answer.choice is True:
        return first_answers
    return first_answers + call_decision(article_input, sentence_id, ["LLM_E002", "LLM_E003"], client, model)


def discover_input_files(input_path):
    """파일 또는 데이터 경로에서 JSON/PKL 입력 파일을 찾는다."""
    input_path = Path(input_path)
    if input_path.is_file():
        return [input_path]
    if not input_path.is_dir():
        raise FileNotFoundError(f"입력 경로가 없습니다: {input_path}")
    files = sorted(path for path in input_path.rglob("*") if path.is_file() and path.suffix.lower() in {".json", ".pkl", ".pickle"})
    if not files:
        raise FileNotFoundError(f"JSON/PKL 파일이 없습니다: {input_path}")
    return files


def _load_file(path):
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8-sig"))
    return pd.read_pickle(path)


def _document_sentences(document):
    return [sentence for paragraph in document.get("paragraph", []) for sentence in paragraph.get("sentence", [])]


def _tagged_entities(sentence):
    return [{"entity_id": f"{sentence['id']}.E{i}", "target_span": match.group(0), "target_type": match.group(2), "rule_evidence": []} for i, match in enumerate(ENTITY_PATTERN.finditer(sentence.get("form", "")), start=1)]


def _normalize_dataframe(frame, press):
    required = {"doc_id", "sentence_id", "form"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{press} PKL에 필요한 컬럼이 없습니다: {sorted(missing)}")
    documents = []
    for doc_id, doc_frame in frame.groupby("doc_id", sort=False):
        sentences = []
        for sentence_id, sentence_frame in doc_frame.groupby("sentence_id", sort=False):
            first = sentence_frame.iloc[0]
            entities = []
            if "entity_id" in frame.columns:
                for _, row in sentence_frame.dropna(subset=["entity_id"]).drop_duplicates("entity_id").iterrows():
                    evidence = [{"rule_id": column, "pattern": row.get(f"{column}_PATTERN", "")} for column in frame.columns if column.startswith("EXT_") and not column.endswith("_PATTERN") and bool(row.get(column, False))]
                    entities.append({"entity_id": row["entity_id"], "target_span": row.get("entity_tagging", ""), "target_type": row.get("entity_type", ""), "rule_evidence": evidence})
            sentence_rules = [{"rule_id": column, "pattern": first.get(f"{column}_PATTERN", "")} for column in frame.columns if column.startswith("EXT_S") and not column.endswith("_PATTERN") and bool(first.get(column, False))]
            sentences.append({"id": sentence_id, "form": first.get("form", ""), "entities": entities, "sentence_rule_evidence": sentence_rules})
        documents.append({"id": doc_id, "metadata": {"publisher": press}, "paragraph": [{"id": f"{doc_id}.paragraph", "sentence": sentences}]})
    return documents


def load_documents(path):
    """언론사 파일을 기사 목록으로 표준화한다."""
    path = Path(path)
    source = _load_file(path)
    if isinstance(source, dict):
        documents = source.get("document", [])
        for document in documents:
            for sentence in _document_sentences(document):
                sentence.setdefault("entities", _tagged_entities(sentence))
                sentence.setdefault("sentence_rule_evidence", [])
        return documents
    if isinstance(source, pd.DataFrame):
        return _normalize_dataframe(source, path.stem)
    raise TypeError(f"지원하지 않는 데이터 형식입니다: {path} ({type(source)})")


def build_catalog(input_path):
    """파일별 기사 수와 문장 수를 반환한다."""
    rows = []
    for path in discover_input_files(input_path):
        documents = load_documents(path)
        rows.append({"press": path.stem, "file": str(path), "format": path.suffix.lower(), "article_count": len(documents), "sentence_count": sum(len(_document_sentences(document)) for document in documents)})
    return pd.DataFrame(rows).sort_values("press").reset_index(drop=True)


def list_articles(input_path, press=None):
    """언론사 파일 안의 기사 목록을 반환한다."""
    rows = []
    for path in discover_input_files(input_path):
        if press is not None and path.stem != press:
            continue
        for index, document in enumerate(load_documents(path)):
            rows.append({"press": path.stem, "file": str(path), "article_index": index, "doc_id": document.get("id"), "title": document.get("metadata", {}).get("title", ""), "sentence_count": len(_document_sentences(document))})
    return pd.DataFrame(rows)


def prepare_document(document):
    """기사 전체 문맥과 Decisions 검토 대상을 구성한다."""
    sentences = _document_sentences(document)
    article_text = "\n".join(f"[{sentence['id']}] {sentence.get('form', '')}" for sentence in sentences)
    review_blocks = []
    for sentence in sentences:
        entities = sentence.get("entities", []) or [{"entity_id": None, "target_span": "", "target_type": "", "rule_evidence": []}]
        entity_lines = [f"- entity_id: {entity.get('entity_id')} | target_span: {entity.get('target_span')} | target_type: {entity.get('target_type')} | rule_evidence: {json.dumps(entity.get('rule_evidence', []), ensure_ascii=False)}" for entity in entities]
        review_blocks.append(f"[{sentence['id']}] {sentence.get('form', '')}\n" f"sentence_rule_evidence: {json.dumps(sentence.get('sentence_rule_evidence', []), ensure_ascii=False)}\n" + "\n".join(entity_lines))
    article_input = "# ARTICLE\n" + article_text + "\n\n# REVIEW_TARGETS\n" + "\n\n".join(review_blocks)
    return article_input, sentences


def _answer_to_dict(answer):
    if hasattr(answer, "model_dump"):
        raw = answer.model_dump()
    elif hasattr(answer, "dict"):
        raw = answer.dict()
    else:
        raw = vars(answer) if hasattr(answer, "__dict__") else str(answer)
    raw = json.loads(json.dumps(raw, ensure_ascii=False, default=str))
    answer_name = getattr(answer, "name", None)
    if isinstance(answer_name, str) and "__" in answer_name:
        answer_name = answer_name.rsplit("__", 1)[-1]
    return {"name": answer_name, "type": getattr(answer, "type", None), "choice": getattr(answer, "choice", None), "value": getattr(answer, "value", None), "raw": raw}


def _write_jsonl(path, rows):
    with path.open("w", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False) + "\n")


def review_file(input_file, output_root, run_id, client=None, model=None, sentence_ids=None):
    """한 언론사 파일을 기사 단위로 실행하고 Decisions 결과를 JSONL로 저장한다."""
    input_file = Path(input_file)
    press = input_file.stem
    output_dir = Path(output_root) / press
    output_dir.mkdir(parents=True, exist_ok=True)
    result_rows = []
    for document in load_documents(input_file):
        article_input, sentences = prepare_document(document)
        selected_ids = set(sentence_ids) if sentence_ids is not None else None
        for sentence in sentences:
            if selected_ids is not None and sentence["id"] not in selected_ids:
                continue
            row = {"run_id": run_id, "press": press, "doc_id": document["id"], "sentence_id": sentence["id"]}
            try:
                answers = run_decision(article_input, sentence["id"], client, model)
                row["status"] = "completed"
                row["answers"] = [_answer_to_dict(answer) for answer in answers]
            except Exception as exc:
                row["status"] = "error"
                row["error"] = str(exc)
            result_rows.append(row)
            print(f"{press} / {document['id']} / {sentence['id']} / {row['status']}")
    _write_jsonl(output_dir / "decision_answers.jsonl", result_rows)
    return result_rows


def run_pipeline(input_path, output_root=None, press=None, article_index=None, sentence_ids=None, model=None):
    """입력 경로에서 기사 단위 Decisions 실행을 시작한다."""
    input_files = discover_input_files(input_path)
    if press is not None:
        input_files = [path for path in input_files if path.stem == press]
    if not input_files:
        raise FileNotFoundError(f"언론사 파일을 찾지 못했습니다: {press}")
    if output_root is None:
        run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        output_root = Path(__file__).resolve().parents[3] / "outputs" / "decision" / run_id
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    run_id = output_root.name
    client = wrap_openai(OpenAI())
    all_rows = []
    for input_file in input_files:
        if article_index is None:
            all_rows.extend(review_file(input_file, output_root, run_id, client, model, sentence_ids))
            continue
        documents = load_documents(input_file)
        if not 0 <= article_index < len(documents):
            raise IndexError(f"article_index 범위: 0~{len(documents) - 1}")
        selected_file = output_root / "_selected_article.pkl"
        pd.to_pickle({"document": [documents[article_index]], "id": documents[article_index]["id"]}, selected_file)
        all_rows.extend(review_file(selected_file, output_root, run_id, client, model, sentence_ids))
        selected_file.unlink()
    _write_jsonl(output_root / "run.jsonl", [{"run_id": run_id, "model": model or DECISION_MODEL, "input_path": str(input_path)}])
    return all_rows


__all__ = ["DECISION_MODEL", "call_decision", "run_decision", "discover_input_files", "load_documents", "build_catalog", "list_articles", "prepare_document", "review_file", "run_pipeline"]
