# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: ner_reviews 적재
# * 설명: NER 검토 결과 Parquet의 테이블 생성, 삭제, 적재
# ***************************************************
import argparse
import pandas as pd
from pathlib import Path
from src.config import get_postgre_connect


BASE_DIR = Path(__file__).resolve().parents[3]
SCHEMA_PATH = BASE_DIR / "src/postgresql/schema/ner_reviews.sql"
PARQUET_NAME = "ner_reviews.parquet"
CSV_NAME = "ner_reviews.csv"
COLUMNS = (
    "run_id", "doc_id", "sentence_id", "entity_id", "target_span", "target_type",
    "corrected_span", "error_lv1", "error_lv2", "reason", "review_needed",
    "llm_review_status", "review_status", "load_dt",
)


def create_table():
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with get_postgre_connect() as connection:
        connection.execute(schema_sql)
    print("ner_reviews 테이블 생성 완료")


def drop_table():
    with get_postgre_connect() as connection:
        connection.execute("DROP TABLE IF EXISTS ner_reviews")
    print("ner_reviews 테이블 삭제 완료")


def _resolve_input(input_path):
    input_path = Path(input_path)
    if not input_path.is_dir():
        return input_path
    parquet_path = input_path / PARQUET_NAME
    csv_path = input_path / CSV_NAME
    if parquet_path.exists():
        return parquet_path
    return csv_path


def make_review_rows(input_path, run_id=None):
    input_path = _resolve_input(input_path)
    data = pd.read_parquet(input_path) if input_path.suffix == ".parquet" else pd.read_csv(input_path)
    if "run_id" not in data.columns:
        if run_id is None:
            raise ValueError("CSV 입력에는 run_id가 없어 run_id 인자가 필요합니다.")
        data["run_id"] = run_id
    for column in COLUMNS:
        if column not in data.columns:
            data[column] = None
    return [
        tuple(None if pd.isna(value) else value for value in row)
        for row in data[list(COLUMNS)].itertuples(index=False, name=None)
    ]


def insert_ner_reviews(input_path, run_id=None):
    rows = make_review_rows(input_path, run_id=run_id)
    if not rows:
        return 0

    placeholders = ", ".join(["%s"] * len(COLUMNS))
    insert_sql = f"""
        INSERT INTO ner_reviews ({', '.join(COLUMNS)})
        VALUES ({placeholders})
        ON CONFLICT (run_id, doc_id, sentence_id, entity_id) DO UPDATE SET
            target_span = EXCLUDED.target_span,
            target_type = EXCLUDED.target_type,
            corrected_span = EXCLUDED.corrected_span,
            error_lv1 = EXCLUDED.error_lv1,
            error_lv2 = EXCLUDED.error_lv2,
            reason = EXCLUDED.reason,
            review_needed = EXCLUDED.review_needed,
            llm_review_status = EXCLUDED.llm_review_status,
            review_status = EXCLUDED.review_status,
            load_dt = EXCLUDED.load_dt
    """

    with get_postgre_connect() as connection:
        with connection.cursor() as cursor:
            cursor.executemany(insert_sql, rows)

    return len(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_path")
    parser.add_argument("--run-id")
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

    row_count = insert_ner_reviews(args.input_path, run_id=args.run_id)
    print(f"ner_reviews 적재 완료: {row_count}건")


if __name__ == "__main__":
    main()
