# -*- coding: utf-8 -*-
"""db 연결"""
#---------------------------------------------------------------------------------------------------------
# 기본 설정 - 라이브러리 불러오기
#---------------------------------------------------------------------------------------------------------
import os
import psycopg
from dotenv import load_dotenv
from pathlib import Path
from psycopg.rows import dict_row


#---------------------------------------------------------------------------------------------------------
# 기본 설정 - 프로젝트 경로 및 환경 변수 불러오기
#---------------------------------------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parents[3]
load_dotenv(BASE_DIR / ".env")


#---------------------------------------------------------------------------------------------------------
# 기능 - 검수 화면용 PostgreSQL 연결
#---------------------------------------------------------------------------------------------------------
def get_postgre_connect():
    """검수 화면용 PostgreSQL 연결을 반환합니다."""
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
