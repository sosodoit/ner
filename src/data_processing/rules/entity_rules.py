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
    tag_data_ = tag_data[tag_data["rule_id"] == 'EXT_E004'].reset_index(drop=True)
    for _, rule in tag_data_.iterrows():
        rule_id = rule["rule_id"]
        sub_rule_id = rule["sub_rule_id"]
        pattern = str(rule["pattern"]).strip()

        # 문장 단위 정규식 탐지
        regex = re.compile(pattern)
        pattern_search = output_data["form"].fillna("").apply(lambda x: [match.group(0) for match in regex.finditer(x)])

        # 기존 태깅 문자열이 탐지 패턴에 포함되는지
        output_data[f"{rule_id}_{sub_rule_id}"] = [
            "Y" if any(entity_tagging in pattern for pattern in patterns) else "N"
            for patterns, entity_tagging in zip(pattern_search, output_data["entity_tagging"])
        ]

        # 검증용: 실제 탐지 패턴
        output_data[f"{rule_id}_{sub_rule_id}_PATTERN"] = [
            ", ".join(pattern for pattern in patterns if entity_tagging in pattern)
            for patterns, entity_tagging in zip(pattern_search, output_data["entity_tagging"])
        ]
    return output_data

# <개체명: EV> 중 DT 표현이 포함된 개체명
def ext_e005(output_data, tag_data):
    tag_data_ = tag_data[tag_data["rule_id"].eq("EXT_E005")]
    ev_mask = output_data["entity_type"].eq("EV")
    entity_names = output_data.loc[ev_mask, "entity_name"].fillna("").astype(str)

    for _, rule in tag_data_.iterrows():
        rule_id = rule["rule_id"]
        sub_rule_id = rule["sub_rule_id"]
        result_col = f"{rule_id}_{sub_rule_id}"
        pattern_col = f"{result_col}_PATTERN"
        regex = re.compile(str(rule["pattern"]).strip())
        pattern_search = entity_names.map(regex.findall)

        output_data[result_col] = "N"
        output_data[pattern_col] = ""
        output_data.loc[ev_mask, result_col] = pattern_search.map(
            lambda matches: "Y" if matches else "N"
        )
        output_data.loc[ev_mask, pattern_col] = pattern_search.map(
            ", ".join
        )

    return output_data

# <개체명: EV> 뒤에 이어지는 EV 표현 탐지
def ext_e006(output_data, tag_data):
    tag_data_ = tag_data[tag_data["rule_id"].eq("EXT_E006")]
    all_tag_regex = re.compile(r"<[^<>:]+?\s*:\s*(?:PS|LC|OG|AF|EV|DT)>")
    ev_tag_regex = re.compile(r":\s*EV>$")
    entity_order_regex = re.compile(r"\.E(\d+)$")

    form_targets = {}
    ev_index = output_data.index[output_data["entity_type"].eq("EV")]
    for idx in ev_index:
        form_value = output_data.at[idx, "form"]
        form = "" if pd.isna(form_value) else str(form_value)
        entity_order_match = entity_order_regex.search(str(output_data.at[idx, "entity_id"]))
        if entity_order_match is None:
            continue

        tagged_entities = form_targets.get(form)
        if tagged_entities is None:
            tagged_entities = {
                "entities": list(all_tag_regex.finditer(form)),
                "rows": [],
            }
            form_targets[form] = tagged_entities

        entity_order = int(entity_order_match.group(1)) - 1
        all_entities = tagged_entities["entities"]
        if entity_order < 0 or entity_order >= len(all_entities):
            continue
        target_entity = all_entities[entity_order]

        if ev_tag_regex.search(target_entity.group(0)):
            tagged_entities.setdefault("rows", []).append(
                (idx, target_entity.start(), target_entity.end())
            )

    for _, rule in tag_data_.iterrows():
        rule_id = rule["rule_id"]
        sub_rule_id = rule["sub_rule_id"]
        result_col = f"{rule_id}_{sub_rule_id}"
        pattern_col = f"{result_col}_PATTERN"
        regex = re.compile(str(rule["pattern"]).strip())
        output_data[result_col] = "N"
        output_data[pattern_col] = ""

        for form, targets in form_targets.items():
            if not targets["rows"]:
                continue
            detected_matches = list(regex.finditer(form))
            if not detected_matches:
                continue

            for idx, target_start, target_end in targets.get("rows", []):
                detected_match = next(
                    (
                        match
                        for match in detected_matches
                        if match.start() <= target_start < target_end <= match.end()
                    ),
                    None,
                )
                if detected_match is not None:
                    output_data.at[idx, result_col] = "Y"
                    output_data.at[idx, pattern_col] = detected_match.group(0)

    return output_data
