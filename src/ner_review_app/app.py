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
    st.markdown("다크모드는 보장 못합니다. 화이트모드 사용 권장드립니다.")
    st.markdown("검수화면에서는 배정받은 기사만 확인이 가능합니다.")
    st.markdown("검수현황에서는 휴먼검수대상의 검수현황 확인이 가능합니다.")
    st.markdown("검수방식에 대한 설명입니다.")
    st.markdown("1.일괄처리: 오태깅이 의심되는 개체명이 있는 문장들이며, 일괄처리 기능을 사용합니다.")
    st.markdown("2.휴먼검수: LLM 검수를 통해 오류 의심이 드는 문장들이며, 휴먼검수합니다.")
    st.markdown("3.계엄기사: 계엄이 포함된 기사들이며, 휴먼검수합니다.")
    st.markdown("검수화면에 대한 설명입니다.")
    st.markdown("좌측 사이드바에서 언론사, 검수방식, 오류유형, 세부유형의 필터링이 있습니다.")
    st.markdown("검수기사목록에 있는 건수는 필터링 결과에 따른 고유 기사 건수입니다.")
    st.markdown("검수기사목록에서 기사를 선택하면 해당 기사에서 오류로 검출된 문장들이 나타납니다.")
    st.markdown("데이터저장 버튼을 클릭하면 데이터베이스에 반영됩니다.")
    st.markdown("페이지를 넘어가기전 데이터저장 버튼을 눌러야합니다.")
    st.markdown("본문에 대한 설명입니다.")
    st.markdown("상단에 언론사, 검수방식, 오류유형은 선택한 필터링에 대한 내용이 나타납니다.")
    st.markdown("원문에 하이라이트된 부분이 오류로 의심되는 영역이며 수정이 필요하면 수정문에서 수정합니다.")
    st.markdown("수정이 필요없으면 이상없음 버튼을, 수정을 했다면 수정완료 버튼을 선택합니다.")
    st.markdown("우측에 의심 되는 오류 유형에 있는 내용을 참고할 수 있습니다.")

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
