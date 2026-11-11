# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: ner_corrected_sentences 적재
# * 설명: 수정 문장 Parquet의 테이블 생성, 삭제, 적재
# ***************************************************
import argparse
import pandas as pd
from pathlib import Path
from src.config import get_postgre_connect


BASE_DIR = Path(__file__).resolve().parents[3]
SCHEMA_PATH = BASE_DIR / "src/postgresql/schema/ner_corrected_sentences.sql"
PARQUET_NAME = "ner_corrected_sentences.parquet"
COLUMNS = (
    "run_id", "doc_id", "sentence_id", "corrected_sentence",
    "human_corrected_sentence", "load_dt",
)


def create_table():
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with get_postgre_connect() as connection:
        connection.execute(schema_sql)
    print("ner_corrected_sentences 테이블 생성 완료")


def drop_table():
    with get_postgre_connect() as connection:
        connection.execute("DROP TABLE IF EXISTS ner_corrected_sentences")
    print("ner_corrected_sentences 테이블 삭제 완료")


def _resolve_parquet(input_path):
    input_path = Path(input_path)
    return input_path / PARQUET_NAME if input_path.is_dir() else input_path


def make_corrected_sentence_rows(input_path):
    data = pd.read_parquet(_resolve_parquet(input_path))
    return [
        tuple(None if pd.isna(value) else value for value in row)
        for row in data[list(COLUMNS)].itertuples(index=False, name=None)
    ]


def insert_ner_corrected_sentences(input_path):
    rows = make_corrected_sentence_rows(input_path)
    if not rows:
        return 0

    insert_sql = """
        INSERT INTO ner_corrected_sentences (
            run_id, doc_id, sentence_id, corrected_sentence,
            human_corrected_sentence, load_dt
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (run_id, doc_id, sentence_id) DO UPDATE SET
            corrected_sentence = EXCLUDED.corrected_sentence,
            human_corrected_sentence = EXCLUDED.human_corrected_sentence,
            load_dt = EXCLUDED.load_dt
    """

    with get_postgre_connect() as connection:
        with connection.cursor() as cursor:
            cursor.executemany(insert_sql, rows)

    return len(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_path")
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

    row_count = insert_ner_corrected_sentences(args.input_path)
    print(f"ner_corrected_sentences 적재 완료: {row_count}건")


if __name__ == "__main__":
    main()
