# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER 룰 파이프라인
# * 작성일: 2026-11-06
# * 설명: 문장 데이터 생성부터 문장 및 개체명 단위 룰 적용까지 실행
# ***************************************************
import pandas as pd

from .entity_rules import ext_e001, ext_e002
from .ner_prepare_data import entity_data, sentence_data
from .sentence_rules import ext_s001, ext_s002, ext_s003


def run_pipeline(input_data, error_data):
    output_data = sentence_data(input_data)

    # 문장 단위 룰 적용
    output_data = ext_s001(output_data)
    output_data = ext_s002(output_data)
    output_data = ext_s003(output_data)

    # 개체명 데이터 추가
    output_data = entity_data(output_data)

    error_df_freq = pd.read_pickle(error_data)

    # 개체명 단위 룰 적용
    output_data = ext_e001(output_data, error_df_freq)
    output_data = ext_e002(output_data)

    output_data.to_pickle(input_data.rsplit(".", 1)[0] + ".pkl")

    return output_data
