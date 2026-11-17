# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER Review App
# * 설명: NER 통계 및 검수 Streamlit 진입점
# ***************************************************
import sys
from pathlib import Path

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

st.set_page_config(
    page_title="---", # NER 검수 시스템
    page_icon="📊",
    layout="wide",
)

st.text("NER 검수 시스템")
st.write("왼쪽 페이지 메뉴에서 전체 통계 또는 NER 검수 화면 선택")
st.caption("전체 통계는 PostgreSQL 집계 결과를 표시하며, NER 검수 화면 구현 예정")


# 페이지 등록
pages = [
    st.Page(
        "pages/1_전체_통계.py",
        title="전체 통계",
        icon="📊",
        default=True,
    ),
    st.Page(
        "pages/2_NER_검수.py",
        title="NER 검수",
        icon="📝",
    ),
]

# 왼쪽 사이드바 메뉴 구성
navigation = st.navigation(pages, position="sidebar")
navigation.run()
