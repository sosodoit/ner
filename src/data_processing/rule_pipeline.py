# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER 룰 파이프라인
# * 작성일: 2026-11-06
# * 설명: 문장 데이터 생성부터 문장 및 개체명 단위 룰 적용까지 실행
# ***************************************************
import json
import pandas as pd
from pathlib import Path
from .prepare.ner_prepare_data import entity_data, sentence_data
from .rules.entity_rules import ext_e001, ext_e002
from .rules.sentence_rules import ext_s001, ext_s002, ext_s003

RULE_COLUMNS = ["EXT_S001", "EXT_S002", "EXT_S003", "EXT_E001", "EXT_E002"]

def run_pipeline(input_data, error_data, output_dir=None):
    
    input_path = Path(input_data)
    review_output_dir = Path(output_dir) if output_dir else input_path.parent / "rule_review"
    review_output_dir.mkdir(parents=True, exist_ok=True)

    # 문장 단위 데이터
    output_data = sentence_data(input_data)

    # 문장 단위 룰 적용
    output_data = ext_s001(output_data)
    output_data = ext_s002(output_data)
    output_data = ext_s003(output_data)

    # 개체명 단위 데이터
    output_data = entity_data(output_data)

    # 오류 이력 데이터
    error_df_freq = pd.read_pickle(error_data)

    # 개체명 단위 룰 적용
    output_data = ext_e001(output_data, error_df_freq)
    output_data = ext_e002(output_data)

    # 검수 대상 기사 저장
    save_review_articles(input_path, review_output_dir / f"{input_path.stem}.pkl", output_data)
    return output_data

# 검수대상기사(룰에 걸린 문장이 하나라도 있는 기사)
def select_review_articles(input_data, rule_data, output_data):
    rule_hits = output_data[rule_data].eq("Y").any(axis=1)
    target_doc_ids = set(output_data.loc[rule_hits, "doc_id"].dropna())

    source = json.loads(Path(input_data).read_text(encoding="utf-8-sig"))
    selected_documents = [
        document
        for document in source["document"]
        if document["id"] in target_doc_ids
    ]

    review_data = {key: value for key, value in source.items() if key != "document"}
    review_data["document"] = selected_documents
    return review_data

# 룰 검출 결과 저장(기사단위)
def save_review_articles(input_data, output_path, output_data):
    review_data = select_review_articles(input_data, RULE_COLUMNS, output_data)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pd.to_pickle(review_data, output_path)
    return review_data
