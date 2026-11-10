# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: PostgreSQL 연결 설정
# * 설명: 공통 PostgreSQL 연결 함수
# ***************************************************
import os
import psycopg
from dotenv import load_dotenv
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")


def get_postgre_connect():
    dsn = os.getenv("POSTGRES_DSN")
    
    if dsn:
        return psycopg.connect(dsn)

    return psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )
