# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER Summary Query
# * 작성일: 2026-11-17
# * 설명: NER 요약 화면에 필요한 PostgreSQL 집계 조회
# ***************************************************
import pandas as pd

from src.config.postgredb import get_postgre_connect


def _fetch_dataframe(cursor, query):
    """SQL 집계 결과만 DataFrame으로 반환"""
    cursor.execute(query)
    rows = cursor.fetchall()
    columns = [column.name for column in cursor.description]
    return pd.DataFrame(rows, columns=columns)


def _build_original_query():
    """언론사별 원본 기사·문장 건수 집계 쿼리"""
    return """
        SELECT
            COALESCE(publisher, '미상') AS publisher,
            COUNT(DISTINCT doc_id)::BIGINT AS article_count,
            COUNT(*)::BIGINT AS sentence_count
        FROM ner_documents
        GROUP BY COALESCE(publisher, '미상')
        ORDER BY publisher
    """


def fetch_summary_rows():
    """DB에서 ner_documents 원본 집계 결과만 조회"""

    with get_postgre_connect() as connection:
        with connection.cursor() as cursor:
            original_df = _fetch_dataframe(cursor, _build_original_query())

    return original_df


# LLM 집계 구현 위치
# ner_reviews 데이터 적재 후 run_id, review_status 등의 집계 기준 확정 후 작성
# 이 곳에 작성
