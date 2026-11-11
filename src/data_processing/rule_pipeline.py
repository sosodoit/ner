# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER 룰 파이프라인
# * 작성일: 2026-11-06
# * 설명: 
# * - 참조 데이터 갱신
# * - 문장 및 개체명 단위 룰 검출
# * - LLM 검수 입력 데이터 생성
# ***************************************************
import json
import argparse
import pandas as pd
from pathlib import Path
from ..config.progress import spand_time
from .prepare.transform import entity_data, sentence_data
from .prepare.error_stats import build_error_stat
from .rules.entity_rules import *
from .rules.sentence_rules import *

BASE_DIR = Path(__file__).resolve().parents[2]

# 참조 데이터 경로
ANALYSIS_DIR = BASE_DIR / "analysis"
TAG_DATA_PATH = ANALYSIS_DIR / "tag_data.pkl"
MISTAG_DATA_PATH = ANALYSIS_DIR / "mistag_data.pkl"
ERROR_DATA_PATH = ANALYSIS_DIR / "error_data.pkl"

# 검수 데이터 경로
LLM_INPUT_DIR = BASE_DIR / "data/filter/llm_input_data"
RULE_OUTPUT_DIR = BASE_DIR / "data/filter/rule_detect_data"

# 디렉터리 생성
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
LLM_INPUT_DIR.mkdir(parents=True, exist_ok=True)
RULE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# 참조 데이터 갱신
def make_refer_data():

    # 오태깅 사전
    mistag_data = pd.read_excel(
        ANALYSIS_DIR / "xlsx/NER_오태깅사전.xlsx",
        sheet_name="오태깅목록",
        usecols="D,F:G"
    )
    mistag_data.columns = ["pattern", "rule_id", "sub_rule_id"]

    # 태깅 사전
    tag_data = pd.read_excel(
        ANALYSIS_DIR / "xlsx/NER_오태깅사전.xlsx",
        sheet_name="태깅목록",
        usecols="D,F:G"
    )
    tag_data.columns = ["pattern", "rule_id", "sub_rule_id"]

    # 오류 이력
    error_data = build_error_stat(ANALYSIS_DIR / "xlsx/NER_개체명검수이력.xlsx")

    # 참조 데이터 저장
    tag_data.to_pickle(TAG_DATA_PATH)
    mistag_data.to_pickle(MISTAG_DATA_PATH)
    error_data.to_pickle(ERROR_DATA_PATH)

# 참조 데이터 로드
def load_refer_data():
    return {
        "error_data": pd.read_pickle(ERROR_DATA_PATH),
        "mistag_data": pd.read_pickle(MISTAG_DATA_PATH),
        "tag_data": pd.read_pickle(TAG_DATA_PATH),
    }

# LLM 검수 입력 데이터 생성
def save_llm_input_data(input_data, output_path, output_data):

    # 룰 컬럼 중 하나라도 Y인 문장 탐지
    rule_columns = [column for column in output_data.columns if column.startswith(("EXT_S", "EXT_E")) and not column.endswith("_PATTERN")]
    rule_hits = output_data[rule_columns].any(axis=1)

    # 중복 기사 ID 제거
    target_doc_ids = set(output_data.loc[rule_hits, "doc_id"].dropna()) 

    # 원본에서 검수 대상 기사 추출
    source = json.loads(Path(input_data).read_text(encoding="utf-8-sig"))
    selected_documents = [
        document
        for document in source["document"]
        if document["id"] in target_doc_ids
    ]

    # 문장별 개체명 정보 구성
    entity_index = {}
    sentence_rule_index = {}
    entity_columns = ["doc_id", "sentence_id", "entity_id", "entity_tagging", "entity_type"]
    entity_rows = output_data.loc[output_data["entity_id"].notna(), entity_columns]
    entity_rule_columns = [
        column for column in output_data.columns
        if column.startswith("EXT_E") and not column.endswith("_PATTERN")
    ]
    sentence_rule_columns = [
        column for column in output_data.columns
        if column.startswith("EXT_S") and not column.endswith("_PATTERN")
    ]
    for row in entity_rows.to_dict("records"):
        key = (row["doc_id"], row["sentence_id"])
        source_row = output_data[
            (output_data["doc_id"] == row["doc_id"])
            & (output_data["sentence_id"] == row["sentence_id"])
            & (output_data["entity_id"] == row["entity_id"])
        ].iloc[0]
        rule_evidence = [
            {
                "rule_id": column,
                "pattern": source_row.get(f"{column}_PATTERN", ""),
            }
            for column in entity_rule_columns
            if bool(source_row[column])
        ]
        entity_index.setdefault(key, []).append({
            "entity_id": row["entity_id"],
            "target_span": row["entity_tagging"],
            "target_type": row["entity_type"],
            "rule_evidence": rule_evidence,
        })

    for row in output_data.drop_duplicates(["doc_id", "sentence_id"]).to_dict("records"):
        key = (row["doc_id"], row["sentence_id"])
        sentence_rule_index[key] = [
            {"rule_id": column, "pattern": row.get(f"{column}_PATTERN", "")}
            for column in sentence_rule_columns
            if bool(row[column])
        ]

    # 원본 문장에 개체명 정보 추가
    for document in selected_documents:
        for paragraph in document["paragraph"]:
            for sentence in paragraph["sentence"]:
                key = (document["id"], sentence["id"])
                sentence["entities"] = entity_index.get(key, [])
                sentence["sentence_rule_evidence"] = sentence_rule_index.get(key, [])

    llm_input_data = {key: value for key, value in source.items() if key != "document"}
    llm_input_data["document"] = selected_documents

    pd.to_pickle(llm_input_data, output_path)

    return llm_input_data

# 룰 검출 파이프라인
def run_pipeline(input_data, run_id, update_refer_data=False):

    input_path = Path(input_data)
    
    # 실행별 저장 경로 생성
    rule_output_dir = RULE_OUTPUT_DIR / run_id
    llm_input_dir = LLM_INPUT_DIR / run_id

    rule_output_dir.mkdir(parents=True, exist_ok=True)
    llm_input_dir.mkdir(parents=True, exist_ok=True)

    # 참조 데이터 로드
    if update_refer_data: make_refer_data()
    refer_data = load_refer_data()

    #----------------------------------------
    # 문장 단위 데이터
    output_data = sentence_data(input_data)

    # 문장 단위 룰 적용
    output_data = ext_s001(output_data)
    output_data = ext_s002(output_data)
    output_data = ext_s003(output_data)

    # 개체명 단위 데이터
    output_data = entity_data(output_data)

    # 개체명 단위 룰 적용
    output_data = ext_e001(output_data, refer_data["error_data"])
    output_data = ext_e002(output_data)
    output_data = ext_e003(output_data, refer_data["mistag_data"])
    output_data = ext_e004(output_data, refer_data["tag_data"])
    output_data = ext_e005(output_data, refer_data["tag_data"])
    output_data = ext_e006(output_data, refer_data["tag_data"])
    #----------------------------------------

    # 룰 검출 결과 저장
    output_data.to_pickle(rule_output_dir / f"{input_path.stem}.pkl")
    
    # LLM 검수 대상 기사 저장
    save_llm_input_data(input_path, llm_input_dir / f"{input_path.stem}.pkl", output_data)
    
    return output_data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NER rule review 데이터 생성")
    parser.add_argument("input_data", type=Path)
    parser.add_argument("--run-id", required=True, help="실행 ID")
    parser.add_argument("--update", action="store_true", help="참조 데이터 갱신")
    args = parser.parse_args()
    
    spand_time(run_pipeline, input_data=args.input_data, run_id=args.run_id, update_refer_data=args.update)
