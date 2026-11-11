# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER 검수 Parquet 저장
# * 작성일: 2026-11-11
# * 수정일: 2026-11-11 (수정 문장 테이블 제거)
# * 설명: 검증된 검수 결과의 PostgreSQL 적재용 Parquet 변환 및 저장
# ***************************************************
import pandas as pd

REVIEW_COLUMNS = [
    "run_id",
    "doc_id",
    "sentence_id",
    "entity_id",
    "target_span",
    "target_type",
    "corrected_span",
    "error_lv1",
    "error_lv2",
    "reason",
    "review_needed",
    "llm_review_status",
    "review_status",
    "load_dt",
    "press",
]

RUN_COLUMNS = [
    "run_id",
    "provider",
    "model",
    "prompt_version",
    "data_version",
    "load_dt",
]

def build_parquet_rows(result, document, run_id, press, load_dt):
    # 검수 결과 행 구성
    return [
        {
            "run_id": run_id,
            "doc_id": document["id"],
            "press": press,
            "load_dt": load_dt,
            **review,
        }
        for review in result["reviews"]
    ]

def save_parquet_results(output_dir, review_rows):
    review_frame = pd.DataFrame(review_rows, columns=REVIEW_COLUMNS)
    review_frame["load_dt"] = pd.to_datetime(review_frame["load_dt"]).dt.date
    review_frame.to_parquet(output_dir / "ner_reviews.parquet", index=False)
    return
    # PostgreSQL 테이블별 Parquet 저장

def save_run_parquet(output_path, run_metadata):
    run_frame = pd.DataFrame([run_metadata], columns=RUN_COLUMNS)
    run_frame["load_dt"] = pd.to_datetime(run_frame["load_dt"]).dt.date
    run_frame.to_parquet(output_path, index=False)
    return
    # 실행 이력 Parquet 저장