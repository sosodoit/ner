# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: 문장 단위 룰
# * 작성일: 2026-11-06
# * 설명: 문장 데이터에 문장 단위 룰을 적용
# ***************************************************

# 계엄이 포함된 문장
def ext_s001(output_data):
    forms = output_data["form"].fillna("").astype(str)
    output_data["EXT_S001"] = forms.str.contains("계엄", na=False)
    return output_data

# 태깅된 개체명이 없는 문장 추출
def ext_s002(output_data):
    pattern = r"<[^<>:]+:\s*(?:PS|LC|OG|AF|EV|DT)>"
    forms = output_data["form"].fillna("").astype(str)
    output_data["EXT_S002"] = ~forms.str.contains(pattern, na=False)
    return output_data

# <개체명: DT>이 연속해서 존재하는 문장
def ext_s003(output_data):
    pattern = r"<[^<>:]+:\s*DT>(?:\s*<[^<>:]+:\s*DT>)+"
    forms = output_data["form"].fillna("").astype(str)
    output_data["EXT_S003"] = forms.str.contains(pattern, na=False)
    return output_data
