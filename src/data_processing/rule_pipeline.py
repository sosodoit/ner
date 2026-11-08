# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER 룰 파이프라인
# * 작성일: 2026-11-06
# * 설명: 문장 데이터 생성부터 문장 및 개체명 단위 룰 적용까지 실행
# ***************************************************
import json
import argparse
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
    review_data = save_review_articles(input_path, review_output_dir / f"{input_path.stem}.pkl", output_data)
    print_pipeline_counts(input_path, output_data, review_data)
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

    # 문장별 개체명 정보 구성
    entity_index = {}
    entity_columns = ["doc_id", "sentence_id", "entity_id", "entity_tagging", "entity_type"]
    entity_rows = output_data.loc[output_data["entity_id"].notna(), entity_columns]
    for row in entity_rows.to_dict("records"):
        key = (row["doc_id"], row["sentence_id"])
        entity_index.setdefault(key, []).append({
            "entity_id": row["entity_id"],
            "target_span": row["entity_tagging"],
            "target_type": row["entity_type"],
        })

    # 원본 문장에 개체명 정보 연결
    for document in selected_documents:
        for paragraph in document["paragraph"]:
            for sentence in paragraph["sentence"]:
                key = (document["id"], sentence["id"])
                sentence["entities"] = entity_index.get(key, [])

    expected_entity_count = entity_rows["entity_id"].drop_duplicates().shape[0]
    saved_entity_count = sum(
        len(sentence.get("entities", []))
        for document in selected_documents
        for paragraph in document["paragraph"]
        for sentence in paragraph["sentence"]
    )

    if expected_entity_count > 0 and saved_entity_count == 0:
        raise RuntimeError(
            "검수용 pickle에 entity 정보가 저장되지 않았습니다. "
            "doc_id/sentence_id 연결을 확인하세요."
        )
                
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

# 결과 요약
def print_pipeline_counts(input_data, output_data, review_data):
    input_path = Path(input_data)
    source_data = json.loads(input_path.read_text(encoding="utf-8-sig"))
    rule_hits = output_data[RULE_COLUMNS].eq("Y").any(axis=1)

    source_sentence_count = output_data[["doc_id", "sentence_id"]].drop_duplicates().shape[0]
    source_entity_count = output_data.loc[output_data["entity_id"].notna(), ["doc_id", "entity_id"]].drop_duplicates().shape[0]
    review_sentence_count = output_data.loc[rule_hits, ["doc_id", "sentence_id"]].drop_duplicates().shape[0]
    review_entity_count = output_data.loc[rule_hits & output_data["entity_id"].notna(), ["doc_id", "entity_id"]].drop_duplicates().shape[0]

    print(
        f"[rule_pipeline] {input_path.name}\n"
        f"└ 원본: 기사 {len(source_data['document'])}건, 문장 {source_sentence_count}건, 개체명 {source_entity_count}건\n"
        f"└ 룰검출: 기사 {len(review_data['document'])}건, 문장 {review_sentence_count}건, 개체명 {review_entity_count}건"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NER rule review 데이터 생성")
    parser.add_argument("input_data", type=Path)
    parser.add_argument("error_data", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    run_pipeline(
        input_data=args.input_data,
        error_data=args.error_data,
        output_dir=args.output_dir,
    )
