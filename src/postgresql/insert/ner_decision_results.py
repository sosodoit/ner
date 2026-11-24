# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: ner_decision_results 적재
# * 설명: 정제된 Decision JSONL을 재가공하여 결과 테이블에 적재
# ***************************************************
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from src.config import get_postgre_connect


BASE_DIR = Path(__file__).resolve().parents[3]
SCHEMA_PATH = BASE_DIR / "src/postgresql/schema/ner_decision_results.sql"
RESULT_FILE_NAME = "results_cleaned.jsonl"


def create_table():
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with get_postgre_connect() as connection:
        connection.execute(schema_sql)
    print("ner_decision_results 테이블 생성 완료")


def drop_table():
    with get_postgre_connect() as connection:
        connection.execute("DROP TABLE IF EXISTS ner_decision_results")
    print("ner_decision_results 테이블 삭제 완료")


def _resolve_input_path(input_path):
    input_path = Path(input_path)
    if input_path.is_dir():
        input_path = input_path / RESULT_FILE_NAME
    if not input_path.is_file():
        raise FileNotFoundError(f"Decision 결과 파일이 없습니다: {input_path}")
    return input_path


def make_decision_df(input_path):
    """results_cleaned.jsonl을 ner_decision_results 적재용 DataFrame으로 변환."""
    jsonl_path = _resolve_input_path(input_path)
    df = pd.read_json(jsonl_path, lines=True)

    # 검출 개체명 및 룰 정보 가공
    df["detected_entities"] = df["existing_entities"].apply(
        lambda x: ", ".join(e["target_span"] for e in x)
    )
    df["candidate_rule_ids"] = df["candidate_rule_ids"].apply(
        lambda x: ", ".join(x)
    )

    # 오류 확률 추출
    def get_probability(probabilities, value):
        return next(
            (p["probability"] for p in probabilities if p["value"] == value),
            np.nan,
        ) if isinstance(probabilities, list) else np.nan

    df["tagging_error_probability"] = df["tagging_error_probabilities"].apply(
        lambda x: get_probability(x, "wrong_major_tag")
    )
    df["tagging_merge_probability"] = df["tagging_merge_probabilities"].apply(
        lambda x: get_probability(x, True)
    )

    # 결측값 검증
    assert df[
        [
            "tagging_error_probability",
            "tagging_error_confidence",
            "tagging_merge_probability",
            "tagging_merge_confidence",
        ]
    ].notna().all().all(), "Decision 결과 결측값 존재"

    # 태그오류 의심 수준
    df["tagging_error_result"] = np.select(
        [
            (df.tagging_error_type == "wrong_major_tag")
            | (df.tagging_error_probability >= 0.4),
            (df.tagging_error_probability >= 0.2)
            | (df.tagging_error_confidence <= 0.2),
        ],
        ["강한 의심", "중간 의심"],
        default="약한 의심",
    )

    # 태깅병합 의심 수준
    df["tagging_merge_result"] = np.select(
        [
            (df.tagging_merge_needed == True)
            | (df.tagging_merge_probability >= 0.1),
            (df.tagging_merge_probability >= 0.01)
            | (df.tagging_merge_confidence <= 0.95),
        ],
        ["강한 의심", "중간 의심"],
        default="약한 의심",
    )

    # 최종 컬럼 선택
    columns = [
        # 매핑 키
        "run_id",
        "data_version",
        "press",
        "doc_id",
        "sentence_id",
        # 검출 정보
        "detected_entities",
        "candidate_rule_ids",
        # 태그 오류 판단
        "tagging_error_probability",
        "tagging_error_confidence",
        "tagging_error_result",
        # 태깅 병합 판단
        "tagging_merge_probability",
        "tagging_merge_confidence",
        "tagging_merge_result",
        # Response 대상
        "review_candidate",
    ]
    return df[columns].copy()


def insert_ner_decision_results(input_path, limit=None, offset=0, chunk_size=1000):
    if chunk_size <= 0:
        raise ValueError("chunk_size는 1 이상이어야 합니다")

    decision_df = make_decision_df(input_path)
    decision_df = decision_df.iloc[offset:]
    if limit is not None:
        decision_df = decision_df.iloc[:limit]

    insert_sql = """
        INSERT INTO ner_decision_results (
            run_id, data_version, press, doc_id, sentence_id,
            detected_entities, candidate_rule_ids,
            tagging_error_probability, tagging_error_confidence, tagging_error_result,
            tagging_merge_probability, tagging_merge_confidence, tagging_merge_result,
            review_candidate
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (data_version, press, doc_id, sentence_id) DO UPDATE SET
            run_id = EXCLUDED.run_id,
            detected_entities = EXCLUDED.detected_entities,
            candidate_rule_ids = EXCLUDED.candidate_rule_ids,
            tagging_error_probability = EXCLUDED.tagging_error_probability,
            tagging_error_confidence = EXCLUDED.tagging_error_confidence,
            tagging_error_result = EXCLUDED.tagging_error_result,
            tagging_merge_probability = EXCLUDED.tagging_merge_probability,
            tagging_merge_confidence = EXCLUDED.tagging_merge_confidence,
            tagging_merge_result = EXCLUDED.tagging_merge_result,
            review_candidate = EXCLUDED.review_candidate,
            updated_at = CURRENT_TIMESTAMP
    """

    total = 0
    rows = decision_df.itertuples(index=False, name=None)
    with get_postgre_connect() as connection:
        with connection.cursor() as cursor:
            batch = []
            for row in rows:
                batch.append(row)
                if len(batch) >= chunk_size:
                    cursor.executemany(insert_sql, batch)
                    total += len(batch)
                    batch = []
            if batch:
                cursor.executemany(insert_sql, batch)
                total += len(batch)

    print(f"ner_decision_results 적재 완료: {total}건")
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

    insert_ner_decision_results(
        args.input_path,
        limit=args.limit,
        offset=args.offset,
        chunk_size=args.chunk_size,
    )


if __name__ == "__main__":
    main()
