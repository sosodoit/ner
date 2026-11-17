# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER Summary Service
# * 작성일: 2026-11-17
# * 설명: NER 언론사별 DB 집계 결과의 화면용 변환
# ***************************************************
from src.ner_review_app.modules.ner_summary_query import fetch_summary_rows


def fetch_summary_data():
    """ner_documents PostgreSQL 집계 결과를 UI에서 사용할 수 있는 형태로 반환"""
    original_df = fetch_summary_rows()

    return {
        "original": original_df.sort_values("publisher").reset_index(drop=True),
        # LLM 집계 구현 위치: ner_reviews 데이터 적재 후 추가
        "llm": None,  # 이 곳에 작성
    }
