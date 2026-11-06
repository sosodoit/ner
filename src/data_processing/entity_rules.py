# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: 개체명 단위 룰
# * 작성일: 2026-11-06
# * 설명: 개체명 데이터에 개체명 단위 룰을 적용
# ***************************************************
import numpy as np
import pandas as pd


def ext_e001(output_data, error_df_freq):
    error_df = error_df_freq[error_df_freq["고빈도여부"] == "Y"].drop_duplicates(
        subset=["temp_entity_name", "entity_type"]
    )[["temp_entity_name", "entity_type"]].reset_index(drop=True)

    # 오류 통계에 존재하는 개체명과 태그에 EXT_E001 컬럼에 'Y' 표시
    output_data["EXT_E001"] = np.where(
        pd.MultiIndex.from_frame(output_data[["temp_entity_name", "entity_type"]])
        .isin(pd.MultiIndex.from_frame(error_df[["temp_entity_name", "entity_type"]])),
        "Y",
        "N"
    )
    return output_data


def ext_e002(output_data):
    # 고빈도여부와 다중태그여부가 Y인 경우 EXT_E002 컬럼에 'Y' 표시
    target_quartiles = ["Q4"]
    output_data["고빈도여부"] = output_data["freq_quartile"].isin(target_quartiles).map({True: "Y", False: "N"})

    tag_count = output_data.groupby("temp_entity_name")["entity_type"].transform("nunique")
    output_data["다중태그여부"] = tag_count.ge(2).map({True: "Y", False: "N"})
    output_data["EXT_E002"] = ((output_data["고빈도여부"] == "Y") & (output_data["다중태그여부"] == "Y")).map({True: "Y", False: "N"})
    return output_data
