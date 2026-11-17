# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER Summary UI
# * 작성일: 2026-11-17
# * 설명: 언론사별 원본 데이터 규모
# ***************************************************
import sys
from pathlib import Path

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ner_review_app.modules.summary_service import fetch_summary_data


@st.cache_data(ttl=600, show_spinner=False)
def load_summary_data():
    """PostgreSQL 집계 결과만 10분간 캐시"""
    return fetch_summary_data()


st.text("전체 통계")
st.caption(
    "원본 데이터는 PostgreSQL의 ner_documents 테이블에서 집계하며, "
    "화면에는 언론사별 집계 결과만 표시"
)

refresh_col, info_col = st.columns([1, 5])
with refresh_col:
    if st.button("집계 새로고침", use_container_width=True):
        load_summary_data.clear()
        st.rerun()
with info_col:
    st.caption("자동 캐시 유효 시간: 10분 · 최신 데이터 확인 시 집계 새로고침 사용")

try:
    with st.spinner("PostgreSQL에서 언론사별 집계 결과 조회 중..."):
        summary_data = load_summary_data()
except Exception as exc:
    st.error(f"PostgreSQL 집계 데이터를 불러오지 못했습니다: {exc}")
    st.stop()


# 1. 원본 데이터 규모
original_df = summary_data["original"]
article_total = int(original_df["article_count"].sum()) if not original_df.empty else 0
sentence_total = int(original_df["sentence_count"].sum()) if not original_df.empty else 0
publisher_total = int(original_df["publisher"].nunique()) if not original_df.empty else 0

st.subheader("원본 데이터 규모 · ner_documents")
metric_cols = st.columns(3)
metric_cols[0].metric("전체 언론사", f"{publisher_total:,}개사")
metric_cols[1].metric("전체 기사", f"{article_total:,}건")
metric_cols[2].metric("전체 문장", f"{sentence_total:,}건")

original_display = original_df.rename(
    columns={
        "publisher": "언론사",
        "article_count": "기사 수",
        "sentence_count": "문장 수",
    }
)
st.dataframe(
    original_display,
    use_container_width=True,
    hide_index=True,
)


# LLM 검수 결과: ner_reviews 데이터 적재 후 구현
st.subheader("LLM 검수 결과 · ner_reviews")
st.info("이 곳에 작성")
# LLM 집계 UI 구현 위치: ner_reviews 데이터 적재 및 집계 기준 확정 후 추가
