# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER Review PostgreSQL 연결
# * 작성일: 2026-11-18
# * 설명: NER 검수 화면에서 사용하는 PostgreSQL 연결 함수
# ***************************************************
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row


BASE_DIR = Path(__file__).resolve().parents[3]
load_dotenv(BASE_DIR / ".env")


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
