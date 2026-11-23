# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: ner_llm_decision 적재
# * 설명: Decision API 정제 결과 JSONL을 문장 단위 테이블에 적재
# ***************************************************
import argparse
import json
from pathlib import Path

from psycopg.types.json import Jsonb

from src.config import get_postgre_connect


BASE_DIR = Path(__file__).resolve().parents[3]
SCHEMA_PATH = BASE_DIR / "src/postgresql/schema/ner_llm_decision.sql"
RESULT_FILE_NAME = "results_cleaned.jsonl"


def create_table():
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with get_postgre_connect() as connection:
        connection.execute(schema_sql)
    print("ner_llm_decision 테이블 생성 완료")


def drop_table():
    with get_postgre_connect() as connection:
        connection.execute("DROP TABLE IF EXISTS ner_llm_decision")
    print("ner_llm_decision 테이블 삭제 완료")


def _resolve_input_path(input_path):
    input_path = Path(input_path)
    if input_path.is_dir():
        input_path = input_path / RESULT_FILE_NAME
    if not input_path.is_file():
        raise FileNotFoundError(f"Decision 결과 파일이 없습니다: {input_path}")
    return input_path


def _number(value):
    return float(value) if value is not None else None


def _json_value(value):
    return Jsonb(value) if value is not None else None


def _make_row(result):
    error = result.get("tagging_error") or {}
    merge = result.get("tagging_merge") or {}
    error_is_error = bool(error.get("is_error"))
    merge_needed = bool(merge.get("needed"))
    confidences = [
        value for value in (error.get("confidence"), merge.get("confidence"))
        if isinstance(value, (int, float))
    ]
    min_confidence = min(confidences) if confidences else None
    low_confidence = min_confidence is not None and min_confidence <= 0.5

    if error_is_error:
        decision_type = "tagging_error"
    elif merge_needed:
        decision_type = "tagging_merge"
    else:
        decision_type = "normal"

    review_reason = []
    if error_is_error:
        review_reason.append("tagging_error")
    if merge_needed:
        review_reason.append("tagging_merge")
    if low_confidence:
        review_reason.append("low_confidence")

    source = result.get("source") or {}
    api = result.get("api") or {}
    return (
        result.get("run_id"),
        result.get("schema_version"),
        result.get("data_version"),
        result.get("press"),
        result.get("doc_id"),
        result.get("sentence_id"),
        result.get("executed_at"),
        result.get("model"),
        result.get("prompt_version"),
        result.get("status"),
        result.get("original_form"),
        decision_type,
        bool(error_is_error or merge_needed or low_confidence),
        bool(low_confidence),
        _number(min_confidence),
        error_is_error,
        error.get("error_type"),
        _number(error.get("confidence")),
        _json_value(error.get("probabilities")),
        merge_needed,
        _number(merge.get("confidence")),
        _json_value(merge.get("probabilities")),
        _json_value(review_reason),
        _json_value(error.get("candidate_rule_ids") or merge.get("candidate_rule_ids")),
        _json_value(source.get("existing_entities")),
        _json_value(source.get("active_rule_evidence")),
        _json_value(api.get("usage")),
        _json_value(api.get("answers")),
    )


def iter_rows(input_path, limit=None, offset=0):
    input_path = _resolve_input_path(input_path)
    selected = 0
    skipped = 0
    with input_path.open(encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            if skipped < offset:
                skipped += 1
                continue
            yield _make_row(json.loads(line))
            selected += 1
            if limit is not None and selected >= limit:
                break


def insert_ner_llm_decision(input_path, limit=None, offset=0, chunk_size=1000):
    if chunk_size <= 0:
        raise ValueError("chunk_size는 1 이상이어야 합니다.")

    insert_sql = """
        INSERT INTO ner_llm_decision (
            run_id, schema_version, data_version, press, doc_id, sentence_id,
            executed_at, model, prompt_version, status, original_form,
            decision_type, review_candidate, low_confidence, min_confidence,
            tagging_error_is_error, tagging_error_type, tagging_error_confidence,
            tagging_error_probabilities, tagging_merge_needed, tagging_merge_confidence,
            tagging_merge_probabilities, review_reason, candidate_rule_ids,
            existing_entities, active_rule_evidence, api_usage, api_answers
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT (run_id, data_version, press, doc_id, sentence_id) DO UPDATE SET
            schema_version = EXCLUDED.schema_version,
            executed_at = EXCLUDED.executed_at,
            model = EXCLUDED.model,
            prompt_version = EXCLUDED.prompt_version,
            status = EXCLUDED.status,
            original_form = EXCLUDED.original_form,
            decision_type = EXCLUDED.decision_type,
            review_candidate = EXCLUDED.review_candidate,
            low_confidence = EXCLUDED.low_confidence,
            min_confidence = EXCLUDED.min_confidence,
            tagging_error_is_error = EXCLUDED.tagging_error_is_error,
            tagging_error_type = EXCLUDED.tagging_error_type,
            tagging_error_confidence = EXCLUDED.tagging_error_confidence,
            tagging_error_probabilities = EXCLUDED.tagging_error_probabilities,
            tagging_merge_needed = EXCLUDED.tagging_merge_needed,
            tagging_merge_confidence = EXCLUDED.tagging_merge_confidence,
            tagging_merge_probabilities = EXCLUDED.tagging_merge_probabilities,
            review_reason = EXCLUDED.review_reason,
            candidate_rule_ids = EXCLUDED.candidate_rule_ids,
            existing_entities = EXCLUDED.existing_entities,
            active_rule_evidence = EXCLUDED.active_rule_evidence,
            api_usage = EXCLUDED.api_usage,
            api_answers = EXCLUDED.api_answers,
            load_dt = CURRENT_TIMESTAMP
    """

    total = 0
    batch = []
    with get_postgre_connect() as connection:
        with connection.cursor() as cursor:
            for row in iter_rows(input_path, limit=limit, offset=offset):
                batch.append(row)
                if len(batch) >= chunk_size:
                    cursor.executemany(insert_sql, batch)
                    total += len(batch)
                    batch = []
            if batch:
                cursor.executemany(insert_sql, batch)
                total += len(batch)

    print(f"ner_llm_decision 적재 완료: {total}건")
    return total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_path")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--chunk-size", type=int, default=1000)
    parser.add_argument("--create-table", action="store_true")
    parser.add_argument("--reset-table", action="store_true")
    args = parser.parse_args()

    if args.create_table and args.reset_table:
        parser.error("--create-table과 --reset-table은 동시에 사용할 수 없습니다.")
    if args.reset_table:
        drop_table()
        create_table()
    elif args.create_table:
        create_table()

    insert_ner_llm_decision(
        args.input_path,
        limit=args.limit,
        offset=args.offset,
        chunk_size=args.chunk_size,
    )


if __name__ == "__main__":
    main()
