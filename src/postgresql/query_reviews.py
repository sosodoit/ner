# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER 검수 결과 PostgreSQL 조회
# * 작성일: 2026-11-08
# * 설명: Streamlit에서 사용할 PostgreSQL 조회 함수
# ***************************************************
import os
import psycopg
from psycopg.rows import dict_row

def get_connection():
    dsn = os.getenv("POSTGRES_DSN")
    if dsn:
        return psycopg.connect(dsn, row_factory=dict_row)

    return psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
        row_factory=dict_row,
    )

# 실행 폴더 목록
def fetch_run_folders():
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT DISTINCT run_folder
            FROM ner_reviews
            ORDER BY run_folder DESC
            """
        ).fetchall()

# 선택한 실행 폴더의 문서 ID 목록을 반환
def fetch_doc_ids(run_folder):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT DISTINCT doc_id
            FROM ner_reviews
            WHERE run_folder = %s
            ORDER BY doc_id
            """,
            (run_folder,),
        ).fetchall()

# 선택한 실행 폴더와 문서의 검수 결과 반환
def fetch_reviews(run_folder, doc_id):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT *
            FROM ner_reviews
            WHERE run_folder = %s
              AND doc_id = %s
            ORDER BY sentence_id, review_id
            """,
            (run_folder, doc_id),
        ).fetchall()
