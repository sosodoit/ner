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
    error_pairs = pd.MultiIndex.from_frame(error_data[["entity_name_no_space", "entity_type"]].drop_duplicates())
    output_pairs = pd.MultiIndex.from_frame(output_data[["entity_name_no_space", "entity_type"]])
    output_data["EXT_E001"] = np.where(output_pairs.isin(error_pairs), "Y", "N")
    return output_data

# 다중 태깅, 고빈도 출현 개체명
def ext_e002(output_data):
    output_data["고빈도여부"] = output_data["freq_quartile"].eq("Q4").map({True: "Y", False: "N"})
    tag_count = output_data.groupby("entity_name_no_space")["entity_type"].transform("nunique")
    output_data["다중태그여부"] = tag_count.ge(2).map({True: "Y", False: "N"})
    output_data["EXT_E002"] = (output_data["고빈도여부"].eq("Y") & output_data["다중태그여부"].eq("Y")).map({True: "Y", False: "N"})
    return output_data

# <개체명: 태그> 중 오태깅 사전에 등록된 개체명
def ext_e003(output_data, mistag_data):
    form_values = output_data["form"].fillna("")
    entity_names = output_data["entity_name"]

    # 동일 패턴의 정규식 탐지 결과 재사용
    pattern_cache = {}

    for rule in mistag_data.itertuples(index=False):
        rule_id = rule.rule_id
        sub_rule_id = rule.sub_rule_id
        pattern = str(rule.pattern).strip()

        if pattern not in pattern_cache:
            regex = re.compile(pattern)
            pattern_cache[pattern] = form_values.map(lambda form: [match.group(0) for match in regex.finditer(form)])

        pattern_search = pattern_cache[pattern]
        result_col = f"{rule_id}_{sub_rule_id}"
        pattern_col = f"{result_col}_PATTERN"

        output_data[result_col] = [
            "Y" if any(entity_name in match for match in matches) else "N"
            for matches, entity_name in zip(pattern_search, entity_names)
        ]

        output_data[pattern_col] = [
            ", ".join(match for match in matches if entity_name in match)
            for matches, entity_name in zip(pattern_search, entity_names)
        ]

    return output_data

# <개체명: DT> 중 구조적 오류가 의심되는 개체명
def ext_e004(output_data, tag_data):
    tag_data_ = tag_data[tag_data["rule_id"].eq("EXT_E004")]
    form_values = output_data["form"].fillna("")
    entity_taggings = output_data["entity_tagging"]

    # 동일 패턴의 정규식 탐지 결과 재사용
    pattern_cache = {}

    for rule in tag_data_.itertuples(index=False):
        rule_id = rule.rule_id
        sub_rule_id = rule.sub_rule_id
        pattern = str(rule.pattern).strip()

        if pattern not in pattern_cache:
            regex = re.compile(pattern)
            pattern_cache[pattern] = form_values.map(lambda form: [match.group(0) for match in regex.finditer(form)])

        pattern_search = pattern_cache[pattern]
        result_col = f"{rule_id}_{sub_rule_id}"
        pattern_col = f"{result_col}_PATTERN"

        output_data[result_col] = [
            "Y" if any(entity_tagging in match for match in patterns) else "N"
            for patterns, entity_tagging in zip(pattern_search, entity_taggings)
        ]

        output_data[pattern_col] = [
            ", ".join(pattern for pattern in patterns if entity_tagging in pattern)
            for patterns, entity_tagging in zip(pattern_search, entity_taggings)
        ]

    return output_data

# <개체명: EV> 중 DT 표현이 포함된 개체명
def ext_e005(output_data, tag_data):
    tag_data_ = tag_data[tag_data["rule_id"].eq("EXT_E005")]
    ev_mask = output_data["entity_type"].eq("EV")

    entity_names = output_data.loc[ev_mask, "entity_name"].fillna("").astype(str)

    for rule in tag_data_.itertuples(index=False):
        rule_id = rule.rule_id
        sub_rule_id = rule.sub_rule_id
        result_col = f"{rule_id}_{sub_rule_id}"
        pattern_col = f"{result_col}_PATTERN"

        regex = re.compile(str(rule.pattern).strip())
        pattern_search = entity_names.map(regex.findall)

        output_data[result_col] = "N"
        output_data[pattern_col] = ""

        output_data.loc[ev_mask, result_col] = pattern_search.map(lambda matches: "Y" if matches else "N")
        output_data.loc[ev_mask, pattern_col] = pattern_search.map(", ".join)

    return output_data

# <개체명: EV> 뒤에 이어지는 EV 표현 탐지
def ext_e006(output_data, tag_data):
    tag_data_ = tag_data[tag_data["rule_id"].eq("EXT_E006")]
    ev_mask = output_data["entity_type"].eq("EV")

    forms = output_data["form"].fillna("")
    entity_taggings = output_data["entity_tagging"].fillna("")

    for rule in tag_data_.itertuples(index=False):
        rule_id = rule.rule_id
        sub_rule_id = rule.sub_rule_id
        result_col = f"{rule_id}_{sub_rule_id}"
        pattern_col = f"{result_col}_PATTERN"

        regex = re.compile(str(rule.pattern).strip())
        pattern_search = forms.map(lambda form: [match.group(0) for match in regex.finditer(form)])

        output_data[result_col] = [
            "Y" if tagging and any(tagging in match for match in matches) else "N"
            for matches, tagging in zip(pattern_search, entity_taggings)
        ]
        
        output_data[pattern_col] = [
            ", ".join(match for match in matches if tagging in match)
            for matches, tagging in zip(pattern_search, entity_taggings)
        ]

        output_data.loc[~ev_mask, [result_col, pattern_col]] = ["N", ""]

    return output_data