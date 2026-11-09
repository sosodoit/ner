# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER 오류 통계
# * 작성일: 2026-11-06
# * 설명: NER 오류 목록에서 태그/개체명별 오류 빈도 집계
# ***************************************************
import re
import pandas as pd

def build_error_stat(input_data):
    pattern = r"<[^<>:]+:\s*(?:PS|LC|OG|AF|EV|DT)>"

    output_data = pd.read_excel(
        input_data,
        sheet_name="오류목록",
        usecols=["개체명", "분류"],
        converters={
            "개체명": lambda value: str(value) if pd.notna(value) else pd.NA,
            "분류": lambda value: str(value).strip() if pd.notna(value) else pd.NA
        }
    )

    # 태깅분리 = 한 셀에 여러 정답 태깅이 있음(개체명, 태그별로 분리)
    error_pairs = []
    for _, row in output_data.iterrows():
        pairs = re.findall(pattern, str(row["개체명"]))

        if pairs:
            error_pairs.extend(pairs)
        elif pd.notna(row["개체명"]) and pd.notna(row["분류"]):
            error_pairs.append((row["개체명"], row["분류"]))

    output_data = pd.DataFrame(error_pairs, columns=["entity_name", "entity_type"])

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

    # 고빈도로 판단할 사분위수 설정
    target_quartiles = ["Q4", "Q3", "Q2", "Q1"]
    output_data["고빈도여부"] = output_data["freq_quartile"].isin(target_quartiles).map({True: "Y", False: "N"})

    return output_data
