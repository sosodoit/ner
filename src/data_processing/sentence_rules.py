# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: 문장 단위 룰
# * 작성일: 2026-11-06
# * 설명: 문장 데이터에 문장 단위 룰을 적용
# ***************************************************


def ext_s001(output_data):
    # form에 '계엄'이 포함된 행에 EXT_S001 컬럼에 'Y' 표시
    output_data["EXT_S001"] = output_data["form"].str.contains("계엄").map({True: "Y", False: "N"})
    return output_data


def ext_s002(output_data):
    # 태깅된 개체명이 없는 행에 EXT_S002 컬럼에 'Y' 표시
    pattern = r"<[^<>:]+:\s*(?:PS|LC|OG|AF|EV|DT)>"
    output_data["EXT_S002"] = output_data["form"].str.contains(pattern).map({True: "N", False: "Y"})
    return output_data


def ext_s003(output_data):
    # DT 태그가 연속해서 존재하는 행에 EXT_S003 컬럼에 'Y' 표시
    pattern = r"<[^<>:]+:\s*DT>(?:\s*<[^<>:]+:\s*DT>)+"
    output_data["EXT_S003"] = output_data["form"].str.contains(pattern).map({True: "Y", False: "N"})
    return output_data
