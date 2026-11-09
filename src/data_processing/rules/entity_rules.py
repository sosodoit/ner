# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: 개체명 단위 룰
# * 작성일: 2026-11-06
# * 설명: 개체명 데이터에 개체명 단위 룰을 적용
# ***************************************************
import re
import numpy as np
import pandas as pd

# 과거 오류 이력의 빈도가 높았던 개체명
def ext_e001(output_data, error_data):
    error_pairs = error_data[["entity_name_no_space", "entity_type"]].drop_duplicates()
    output_data["EXT_E001"] = np.where(pd.MultiIndex.from_frame(output_data[["entity_name_no_space", "entity_type"]])
                                .isin(pd.MultiIndex.from_frame(error_pairs)), "Y", "N")
    return output_data

# 다중 태깅, 고빈도 출현 개체명
def ext_e002(output_data):
    target_quartiles = ["Q4"]
    output_data["고빈도여부"] = output_data["freq_quartile"].isin(target_quartiles).map({True: "Y", False: "N"})
    tag_count = output_data.groupby("entity_name_no_space")["entity_type"].transform("nunique")
    output_data["다중태그여부"] = tag_count.ge(2).map({True: "Y", False: "N"})
    output_data["EXT_E002"] = ((output_data["고빈도여부"] == "Y") & (output_data["다중태그여부"] == "Y")).map({True: "Y", False: "N"})
    return output_data

# <개체명: 태그> 중 오태깅 사전에 등록된 개체명
def ext_e003(output_data, mistag_data):
    for _, rule in mistag_data.iterrows():
        rule_id = rule["rule_id"]
        sub_rule_id = rule["sub_rule_id"]
        pattern = str(rule["pattern"]).strip()

        # 문장 단위 정규식 탐지
        regex = re.compile(pattern)
        pattern_search = output_data["form"].fillna("").apply(lambda x: [match.group(0) for match in regex.finditer(x)])

        # 개체명 단위 탐지 여부
        output_data[f"{rule_id}_{sub_rule_id}"] = [
            "Y" if any(entity_name in match for match in matches) else "N"
            for matches, entity_name in zip(pattern_search, output_data["entity_name"])
        ]

        # 검증용: 실제 탐지 패턴
        output_data[f"{rule_id}_{sub_rule_id}_PATTERN"] = [
            ", ".join(match for match in matches if entity_name in match)
            for matches, entity_name in zip(pattern_search, output_data["entity_name"])
        ]
    return output_data

# <개체명: DT> 중 구조적 오류가 의심되는 개체명
def ext_e004(output_data, tag_data):
    return 1

# ext_e005
def ext_e005():
    return 1

# ext_e006
def ext_e006():
    return 1

# ext_e007
def ext_e007():
    return 1