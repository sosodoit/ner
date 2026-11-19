# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER Review App
# * 설명: NER 통계 및 검수 Streamlit 진입점
# ***************************************************
import sys
import streamlit as st
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

st.set_page_config(
    page_title="NER 검수",
    page_icon="📖",
    layout="wide",
)

# 첫 화면
def home():
    st.info("검수방법")

# 페이지 등록
pages = [
    st.Page(
        home,
        title="홈",
        icon="ℹ️",
        default=True,
    ),
    st.Page(
        "pages/1_ner.py",
        title="NER 검수",
        icon="1️⃣",
    ),
    st.Page(
        "pages/2_dashboard.py",
        title="검수 현황",
        icon="2️⃣",
    ),
]

# 왼쪽 사이드바 메뉴 구성
navigation = st.navigation(pages, position="sidebar")
navigation.run()
