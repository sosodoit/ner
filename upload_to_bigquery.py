# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER 검수 결과 BigQuery 적재
# * 작성일: 2026-10-25
# * 설명: 데이터 버전별 NER 검수 결과를 BigQuery 테이블에 적재
# ***************************************************
import os
import json
import hashlib
import argparse
import logging
import tempfile
from dotenv import load_dotenv
from pathlib import Path
from google.cloud import bigquery

# ***************************************************
# * 설정
# ***************************************************
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
DATASET_ID = os.getenv("GCP_DATASET_ID")
TABLE_NAME = os.getenv("GCP_TABLE_NAME")

OUTPUT_DIR = BASE_DIR / "outputs"
LOG_FILE = BASE_DIR / "upload_to_bigquery.log"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler(),])

# ***************************************************
# * 테이블 스키마
# ***************************************************
SCHEMA = [
    bigquery.SchemaField("row_key", "STRING"),
    bigquery.SchemaField("run_folder", "STRING"),
    bigquery.SchemaField("publisher", "STRING"),
    bigquery.SchemaField("doc_id", "STRING"),
    bigquery.SchemaField("provider", "STRING"),
    bigquery.SchemaField("model", "STRING"),
    bigquery.SchemaField("sentence_id", "STRING"),
    bigquery.SchemaField("target_span", "STRING"),
    bigquery.SchemaField("corrected_span", "STRING"),
    bigquery.SchemaField("error_lv1", "STRING"),
    bigquery.SchemaField("error_lv2", "STRING"),
    bigquery.SchemaField("reason", "STRING"),
    bigquery.SchemaField("review_needed", "BOOL"),
]

# ***************************************************
# * JSON/JSONL 파싱
# ***************************************************
def iter_json_objects(file_path):
    text = file_path.read_text(encoding="utf-8-sig")
    decoder = json.JSONDecoder()
    position = 0

    while position < len(text):
        while position < len(text) and text[position].isspace():
            position += 1

        if position >= len(text):
            break

        article, position = decoder.raw_decode(text, position)
        yield article


def flatten_reviews(file_path):
    run_folder = file_path.parent.name
    publisher = file_path.stem

    for article_idx, article in enumerate(iter_json_objects(file_path)):
        reviews = article.get("result", {}).get("reviews", [])

        for review_idx, review in enumerate(reviews):
            identity = (
                f"{run_folder}|{publisher}|"
                f"{article.get('doc_id', '')}|"
                f"{article_idx}|{review_idx}"
            )

            row_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()

            yield {
                "row_key": row_key,
                "run_folder": run_folder,
                "publisher": publisher,
                "doc_id": article.get("doc_id"),
                "provider": article.get("provider"),
                "model": article.get("model"),
                "sentence_id": review.get("sentence_id"),
                "target_span": review.get("target_span"),
                "corrected_span": review.get("corrected_span"),
                "error_lv1": review.get("error_lv1"),
                "error_lv2": review.get("error_lv2"),
                "reason": review.get("reason"),
                "review_needed": review.get("review_needed", False),
            }


# ***************************************************
# * JSON/JSONL 파일 하나를 리뷰 단위로 변환하여 적재
# * - 지정한 데이터 버전의 파일만 처리
# * - 동일 데이터 버전 재적재 전 BigQuery 기존 데이터 삭제 필요
# ***************************************************
def upload_file(file_path, client, table_id):
    relative_path = file_path.relative_to(BASE_DIR)
    count = 0

    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".jsonl", delete=False) as temp:
            temp_path = Path(temp.name)

            for row in flatten_reviews(file_path):
                temp.write(json.dumps(row, ensure_ascii=False) + "\n")
                count += 1

        if count == 0:
            logging.info(f"리뷰없음: {relative_path}")
            return

        config = bigquery.LoadJobConfig(schema=SCHEMA, source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON, write_disposition=bigquery.WriteDisposition.WRITE_APPEND)

        with temp_path.open("rb") as f:
            job = client.load_table_from_file(f, table_id, job_config=config)

        job.result()
        logging.info(f"적재완료: {relative_path} ({count:,}개 리뷰)")

    finally:
        if "temp_path" in locals():
            temp_path.unlink(missing_ok=True)


# ***************************************************
# * 실행
# ***************************************************
def main():
    parser = argparse.ArgumentParser(description="NER 검수 결과 BigQuery 적재")
    parser.add_argument("data_version", help="적재할 outputs 하위 데이터 버전 폴더명")

    args = parser.parse_args()
    run_dir = OUTPUT_DIR / args.data_version

    client = bigquery.Client(project=PROJECT_ID)
    table_id = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_NAME}"
    client.create_table(bigquery.Table(table_id, schema=SCHEMA), exists_ok=True)
    files = sorted(run_dir.glob("*.jsonl"))
    logging.info(f"대상파일: {len(files)}개")

    for file_path in files:
        try:
            upload_file(file_path, client, table_id)
        except Exception as exc:
            logging.error(f"실패: {file_path} | {exc} | 해당 파일을 건너뛰고 다음 파일 처리")

    logging.info("처리종료")


if __name__ == "__main__":
    main()
