# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: LLM 검수 결과 적재
# * 작성일: 2026-10-25
# * 설명: 데이터 버전 기준 빅쿼리 테이블 적재 
# ***************************************************
import os
import re
import json
import logging
import argparse
import tempfile
from dotenv import load_dotenv
from pathlib import Path
from zoneinfo import ZoneInfo
from datetime import datetime
from google.cloud import bigquery

# ***************************************************
# * 설정
# ***************************************************
BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
DATASET_ID = os.getenv("GCP_DATASET_ID")
TABLE_NAME = os.getenv("GCP_TABLE_NAME")

DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "outputs"
LOG_FILE = BASE_DIR / "logs" / "load_reviews.log"
ENTITY_PATTERN = re.compile(r"<([^:>]+):\s*(PS|LC|OG|AF|DT|EV)>", re.IGNORECASE)

# ***************************************************
# * 테이블 스키마
# ***************************************************
SCHEMA = [
    bigquery.SchemaField("run_folder", "STRING"),
    bigquery.SchemaField("provider", "STRING"),
    bigquery.SchemaField("model", "STRING"),
    bigquery.SchemaField("prompt_version", "STRING"),
    bigquery.SchemaField("dataset_version", "STRING"),
    bigquery.SchemaField("press", "STRING"),
    bigquery.SchemaField("doc_id", "STRING"),
    bigquery.SchemaField("sentence_id", "STRING"),
    # 기존 review_id 컬럼에 entity_id(예: S001.E1)를 저장
    bigquery.SchemaField("review_id", "STRING"),
    bigquery.SchemaField("source_sentence", "STRING"),
    bigquery.SchemaField("llm_review_status", "STRING"),
    bigquery.SchemaField("review_status", "STRING"),
    bigquery.SchemaField("target_span", "STRING"),
    bigquery.SchemaField("target_type", "STRING"),
    bigquery.SchemaField("corrected_span", "STRING"),
    bigquery.SchemaField("error_lv1", "STRING"),
    bigquery.SchemaField("error_lv2", "STRING"),
    bigquery.SchemaField("reason", "STRING"),
    bigquery.SchemaField("review_needed", "BOOL"),
    bigquery.SchemaField("load_dt", "DATE"),
]

# ***************************************************
# * 로그 및 환경 설정
# ***************************************************
def configure_logging():
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )

def validate_config():
    required = {
        "GCP_PROJECT_ID": PROJECT_ID,
        "GCP_DATASET_ID": DATASET_ID,
        "GCP_TABLE_NAME": TABLE_NAME,
    }

    missing = [
        key for key, value in required.items()
        if not value
    ]

    if missing:
        raise ValueError(
            f"필수 환경변수 누락: {', '.join(missing)}"
        )

def create_bigquery_client():
    return bigquery.Client(project=PROJECT_ID)

def get_table_id():
    return f"{PROJECT_ID}.{DATASET_ID}.{TABLE_NAME}"

# ***************************************************
# * 원본 데이터 색인
# ***************************************************
def load_source_index(run_dir, publisher):
    dataset_version = run_dir.parent.name
    source_file = DATA_DIR / dataset_version / f"{publisher}.json"

    if not source_file.is_file():
        raise FileNotFoundError(
            f"원본 JSON 없음: {source_file}"
        )

    source = json.loads(
        source_file.read_text(encoding="utf-8-sig")
    )

    index = {}

    for document in source.get("document", []):
        doc_id = document.get("id")

        for paragraph in document.get("paragraph", []):
            for sentence in paragraph.get("sentence", []):
                form = sentence.get("form", "")

                index[(doc_id, sentence.get("id"))] = {
                    "source_sentence": form,
                    "entities": [
                        {
                            "entity_id": None,
                            "target_span": match.group(0),
                            "target_type": match.group(2).upper(),
                        }
                        for match in ENTITY_PATTERN.finditer(form)
                    ],
                }

    return dataset_version, index

# ***************************************************
# * 리뷰 행 변환
# ***************************************************
def build_base_review(article, review, source, run_folder, dataset_version, press, load_dt):
    review_status = review.get("review_status", "error")
    is_normal = review_status == "normal"

    return {
        "run_folder": run_folder,
        "provider": article.get("provider"),
        "model": article.get("model"),
        "prompt_version": article.get("prompt_version"),
        "dataset_version": dataset_version,
        "press": press,
        "doc_id": article.get("doc_id"),
        "sentence_id": review.get("sentence_id"),
        "entity_id": review.get("entity_id"),
        "source_sentence": source["source_sentence"],
        "llm_review_status": review.get("llm_review_status", "unreviewed"),
        "review_status": review_status,
        "corrected_span": (None if is_normal else review.get("corrected_span")),
        "error_lv1": (None if is_normal else review.get("error_lv1")),
        "error_lv2": (None if is_normal else review.get("error_lv2")),
        "reason": review.get("reason"),
        "review_needed": review.get("review_needed", False),
        "load_dt": load_dt,
    }

# 정상건 개체명 단위 변환
def build_normal_rows(review, entities):
    review_entity_id = review.get("entity_id")
    review_data = {
        key: value
        for key, value in review.items()
        if key != "entity_id"
    }

    if review_entity_id is not None:
        entities = [
            entity for entity in entities
            if entity.get("entity_id") == review_entity_id
        ]

    if not entities:
        return [{
            **review_data,
            "review_id": review_entity_id,
            "target_span": None,
            "target_type": None,
        }]

    return [
        {
            **review_data,
            "review_id": entity.get("entity_id"),
            "target_span": entity["target_span"],
            "target_type": entity["target_type"],
        }
        for entity in entities
    ]

# 개체명 연결
def build_error_row(review, entities):
    review_entity_id = review.get("entity_id")
    target_span = (review.get("target_span") or "").strip()
    review_data = {
        key: value
        for key, value in review.items()
        if key != "entity_id"
    }

    if review_entity_id:
        matches = [
            entity for entity in entities
            if entity.get("entity_id") == review_entity_id
        ]
    else:
        matches = [
            entity
            for entity in entities
            if entity["target_span"] == target_span
        ]

    # 기존 원본 개체명 연결
    if len(matches) == 1:
        entity = matches[0]

        return {
            **review_data,
            "review_id": entity.get("entity_id"),
            "target_span": entity["target_span"],
            "target_type": entity["target_type"],
        }

    # 동일 명칭의 원본 개체명이 여러 개 존재하는 경우
    if len(matches) > 1:
        logging.error(
            f"원문 개체명 중복 연결 실패: target_span={target_span}"
        )
        return None

    # 원본에 없는 신규 후보는 entity_id 없이 저장
    corrected_match = ENTITY_PATTERN.search(
        review.get("corrected_span") or ""
    )

    target_type = (
        corrected_match.group(2).upper()
        if corrected_match
        else None
    )

    return {
        **review_data,
        "review_id": review_entity_id,
        "target_span": "",
        "target_type": target_type,
    }

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

# ***************************************************
# * 검수 결과 경로 및 데이터 변환
# ***************************************************
def resolve_run_dir(file_path):
    for parent in file_path.parents:
        if parent.name.startswith("run_"):
            return parent

    raise ValueError(
        f"지원하지 않는 검수 결과 경로: {file_path}"
    )


def flatten_reviews(file_path):
    run_dir = resolve_run_dir(file_path)
    run_folder = f"{run_dir.parent.name}/{run_dir.name}"

    press = (
        file_path.parent.name
        if file_path.name == "reviews.jsonl"
        else file_path.stem
    )

    dataset_version, source_index = load_source_index(run_dir, press)

    load_dt = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()

    for article in iter_json_objects(file_path):
        reviews = article.get("result", {}).get("reviews", [])

        for review in reviews:
            sentence_id = review.get("sentence_id")
            doc_id = article.get("doc_id")

            source = source_index.get((doc_id, sentence_id))

            if source is None:
                logging.error(
                    f"원문 연결 실패: doc_id={doc_id} "
                    f"| sentence_id={sentence_id}"
                )
                continue

            base_review = build_base_review(
                article=article,
                review=review,
                source=source,
                run_folder=run_folder,
                dataset_version=dataset_version,
                press=press,
                load_dt=load_dt,
            )

            # data_processing에서 전달된 entity_id 우선 사용
            entities = review.get("entities", source["entities"])

            # 정상 판정
            if base_review["review_status"] == "normal":
                yield from build_normal_rows(base_review, entities)
                continue

            # 오류 판정
            row = build_error_row(
                {
                    **base_review,
                    "target_span": review.get("target_span"),
                },
                entities,
            )

            if row is not None:
                yield row

# ***************************************************
# * 적재 대상 파일 탐색
# ***************************************************
def find_review_files(input_dir):
    if not input_dir.is_dir():
        raise FileNotFoundError(
            f"적재 대상 디렉터리 없음: {input_dir}"
        )

    if input_dir.name.startswith("run_"):
        candidates = [
            *input_dir.glob("*.jsonl"),
            *input_dir.glob("reports/*/reviews.jsonl"),
        ]

    else:
        candidates = [
            *input_dir.glob("*.jsonl"),
        ]

        for run_dir in sorted(input_dir.glob("run_*")):
            candidates.extend(run_dir.glob("*.jsonl"))
            candidates.extend(
                run_dir.glob("reports/*/reviews.jsonl")
            )

    return sorted(set(candidates))

# ***************************************************
# * BigQuery 적재
# ***************************************************
def create_load_config():
    return bigquery.LoadJobConfig(
        schema=SCHEMA,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        schema_update_options=[bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION],
    )

def write_temp_jsonl(file_path):
    count = 0
    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".jsonl",
            delete=False,
        ) as temp:
            temp_path = Path(temp.name)

            for row in flatten_reviews(file_path):
                temp.write(
                    json.dumps(row, ensure_ascii=False) + "\n"
                )
                count += 1

        return temp_path, count

    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def upload_file(file_path, client, table_id):
    relative_path = file_path.relative_to(BASE_DIR)
    temp_path = None

    try:
        temp_path, count = write_temp_jsonl(file_path)

        if count == 0:
            logging.info(f"리뷰없음: {relative_path}")
            return

        config = create_load_config()

        with temp_path.open("rb") as file:
            job = client.load_table_from_file(
                file,
                table_id,
                job_config=config,
            )

        job.result()

        logging.info(
            f"적재완료: {relative_path} ({count:,}개 리뷰)"
        )

    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def validate_existing_table_schema(client, table_id):
    table = client.get_table(table_id)
    fields = {field.name: field.field_type for field in table.schema}

    if fields.get("review_id") != "STRING":
        raise ValueError(
            f"{table_id}.review_id 타입이 STRING이 아닙니다: "
            f"현재={fields.get('review_id')}. "
            "기존 테이블을 STRING 타입으로 마이그레이션한 뒤 다시 실행하세요."
        )


# ***************************************************
# * 실행
# ***************************************************
def main():
    parser = argparse.ArgumentParser(description="NER 검수 결과 BigQuery 적재")

    parser.add_argument(
        "run_path",
        help=(
            "적재할 outputs 하위 경로 "
            "(예: poc_20261027_194000/run_20261028_132100)"
        ),
    )

    args = parser.parse_args()

    configure_logging()
    validate_config()

    run_dir = (OUTPUT_DIR / args.run_path).resolve()

    # outputs 외부 경로 접근 방지
    try:
        run_dir.relative_to(OUTPUT_DIR.resolve())
    except ValueError:
        raise ValueError(
            f"outputs 외부 경로는 적재할 수 없음: {run_dir}"
        )

    client = create_bigquery_client()
    table_id = get_table_id()

    # 테이블이 없으면 생성
    client.create_table(
        bigquery.Table(table_id, schema=SCHEMA),
        exists_ok=True,
    )
    validate_existing_table_schema(client, table_id)

    files = find_review_files(run_dir)

    logging.info(f"대상파일: {len(files)}개")

    for file_path in files:
        try:
            upload_file(file_path, client, table_id)

        except Exception as exc:
            logging.error(
                f"실패: {file_path} | {exc} "
                "| 해당 파일을 건너뛰고 다음 파일 처리"
            )

    logging.info("처리종료")


if __name__ == "__main__":
    main()
