# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER 검수 결과 PostgreSQL 적재
# * 작성일: 2026-11-08
# * 설명: BigQuery와 동일한 flat row를 PostgreSQL에 적재
# ***************************************************
import os
import logging
import psycopg
import argparse
from pathlib import Path
from dotenv import load_dotenv
from src.bigquery.load_reviews import find_review_files, flatten_reviews

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = BASE_DIR / "outputs"
load_dotenv(BASE_DIR / ".env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

COLUMNS = (
    "run_folder", "provider", "model", "prompt_version", "dataset_version",
    "press", "doc_id", "sentence_id", "review_id", "source_sentence",
    "llm_review_status", "review_status", "target_span", "target_type",
    "corrected_span", "error_lv1", "error_lv2", "reason", "review_needed",
    "load_dt",
)

def get_connection():
    dsn = os.getenv("POSTGRES_DSN")
    if dsn:
        return psycopg.connect(dsn)

    return psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )


def load_run(run_path):
    run_dir = OUTPUT_DIR / run_path
    files = find_review_files(run_dir)
    rows = [
        tuple(row.get(column) for column in COLUMNS)
        for file_path in files
        for row in flatten_reviews(file_path)
    ]

    if not rows:
        logging.info("적재할 검수 결과가 없습니다: %s", run_dir)
        return 0

    run_folder = rows[0][0]
    placeholders = ", ".join(["%s"] * len(COLUMNS))
    insert_sql = f"""
        INSERT INTO ner_reviews ({', '.join(COLUMNS)})
        VALUES ({placeholders})
    """

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM ner_reviews WHERE run_folder = %s", (run_folder,))
            cursor.executemany(insert_sql, rows)

    logging.info("PostgreSQL 적재 완료: %s (%s건)", run_folder, len(rows))
    return len(rows)

def main():
    parser = argparse.ArgumentParser(description="NER 검수 결과 PostgreSQL 적재")
    parser.add_argument("run_path", help="적재할 outputs 하위 경로")
    args = parser.parse_args()
    load_run(args.run_path)


if __name__ == "__main__":
    main()
