"""세 검수 화면이 공유하는 배정 기사 목록·본문 조회 캐시."""
import streamlit as st

from src.ner_review_app.modules.postgredb import get_postgre_connect


@st.cache_data(ttl=3600, max_entries=64, show_spinner=False)
def load_review_rows(query, params):
    with get_postgre_connect() as conn:
        return conn.execute(query, params).fetchall()
