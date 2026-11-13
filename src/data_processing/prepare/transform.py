# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: 데이터 변환
# * 작성일: 2026-11-06      
# * 설명: 원본 데이터를 룰 검출용 데이터프레임으로 변환
# ***************************************************
import json
from pathlib import Path

import pandas as pd

def sentence_data(input_data):
    with open(input_data, "r", encoding="utf-8") as f:
        data = json.load(f)
    source_id = data.get("id", Path(input_data).stem)
    rows = []
    for doc in data["document"]:
        for paragraph in doc["paragraph"]:
            for sentence in paragraph["sentence"]:
                rows.append({
                    "id": source_id,
                    "doc_id": doc["id"],
                    "sentence_id": sentence["id"],
                    "form": sentence["form"]
                })
    output_data = pd.DataFrame(rows)
    return output_data

def entity_data(input_data):
    pattern = r"<[^<>:]+:\s*(?:PS|LC|OG|AF|EV|DT)>"
    output_data = input_data.copy()

    # <개체명: 태그> 추출
    output_data["entity_tagging"] = output_data["form"].str.findall(pattern)
    output_data = output_data.explode("entity_tagging", ignore_index=True)
    has_entity = output_data["entity_tagging"].notna()

    # 개체명 ID 생성
    output_data["entity_id"] = None
    output_data.loc[has_entity, "entity_id"] = (output_data.loc[has_entity, "sentence_id"] + ".E" + output_data.loc[has_entity].groupby("sentence_id").cumcount().add(1).astype(str))

    # 개체명 추출
    output_data["entity_name"] = output_data["entity_tagging"].str.extract(r"<(.*?):")

    # 태그 추출
    output_data["entity_type"] = output_data["entity_tagging"].str.extract(r":\s*(PS|LC|OG|AF|EV|DT)>")

    # 개체명 내부의 모든 공백 제거
    output_data["entity_name_no_space"] = output_data["entity_name"].str.replace(r"\s+", "", regex=True)

    # 태그별 개체명 빈도 집계
    freq = (
        output_data.dropna(subset=["entity_name_no_space", "entity_type"])
          .groupby(["entity_type", "entity_name_no_space"])
          .size()
          .rename("entity_freq")
          .reset_index()
    )
    output_data = output_data.merge(freq, on=["entity_type", "entity_name_no_space"], how="left")

    # 사분위수 집계
    quartile_code = pd.qcut(output_data["entity_freq"], q=4, labels=False, duplicates="drop")
    output_data["freq_quartile"] = quartile_code.map({0: "Q1", 1: "Q2", 2: "Q3", 3: "Q4"})

    return output_data
