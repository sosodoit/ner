# -*- coding: utf-8 -*-
"""NER 검수 화면"""
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
    st.markdown("**🔥 NER 검수 시작하기**")
    st.markdown("🔥 **화이트 모드** 사용을 권장합니다.")
    st.markdown("🔥 진행 순서: **휴먼 검수** 선택 >> 기사 선택 >> 문장 확인 및 수정 >> 저장")
    st.markdown("")
    st.markdown("**💡 검수 화면에 대한 설명입니다.**")
    st.markdown("""
    | 메뉴 | 검수할 내용 | 작업 방법 |
    | --- | --- | --- |
    | **휴먼검수** | LLM이 판정한 결과와 오류 의심 문장 | 원문과 수정 제안을 비교해 문장별로 판단합니다. |
    | **계엄기사** | 계엄 관련 기사의 검수 대상 문장 | 문맥을 확인하고 개체명과 태그를 직접 검수합니다. |
    | **일괄처리** | 오태깅이 의심되어 태그 제거 대상으로 모은 문장 | 현재 페이지의 일괄처리 결과를 확인한 뒤 일괄저장합니다. |
    """)
    st.markdown("")
    st.markdown("**💡 조회 조건에 대한 설명입니다.**")
    with st.container(border=True):
        st.markdown("""
        1. **담당** `언론사` 선택
        2. **검수결과**는 `오류` 선택
        3. **검수상태**는 `미완료` 선택
        4. 필요한 경우 `기사ID 또는 문장ID 검색` `오류유형` 선택
        5. `개체명 목록 기준 검수`를 통해 **출현빈도가 높은 개체명**을 우선적으로 검수
        6. **기사목록**에서 기사를 선택하세요. 목록의 건수는 현재 조건에 맞는 고유 기사 수입니다.

        ※ 휴먼검수의 `검수결과(전체·오류·정상)`는 LLM 판정에 따른 기사 분류입니다.

        ※ 휴먼검수의 `검수 상태(전체·미완료·완료)`는 사람이 검수를 마쳤는지를 나타냅니다.
        """)
    st.markdown("")
    st.markdown("**💡 검수가 완료된 문장을 저장하는 방법에 대한 설명입니다.**")
    with st.container(border=True):
        st.markdown("""
        1. 원문의 **강조 표시**와 오른쪽의 **검수 참고 정보**를 함께 확인하여 검수합니다.
        2. 수정이 필요하면 **수정문**을 편집하고 `수정완료`를 누르세요. 수정할 필요가 없으면 `이상없음`을 누르세요.
        3. 휴먼검수와 계엄기사는 `수정완료`를 누르면 해당 문장의 결과가 저장됩니다.**이미 완료한 문장**을 다시 고쳤다면 `재수정완료`를 누르세요.
        4. 문맥이 더 필요하면 `전체 기사보기`를 누르세요. `검수 대상만 보기`를 누르면 대상 문장 중심으로 돌아옵니다.

        ※ 기사의 검수 대상 문장을 모두 저장 완료하면 해당 기사가 완료로 분류됩니다.

        ※ 일괄처리 검증은 소희가 합니다.
        """)
    st.markdown("")
    st.markdown("**💡 기타 화면에 대한 설명입니다.**")
    st.markdown("""
    | 메뉴 | 사용할 때 |
    | --- | --- |
    | **검수현황** | 언론사별, 언론사·검수방식별 진행 상황을 확인할 때 사용합니다. 담당자 배정 탭에서는 조건별 배정/재배정이 필요할 때 사용합니다. |
    | **샘플검수** | 원본 기사 중 전체 검수 대상에 포함되지 않은 기사를 표본으로 확인할 때 사용합니다. |
    | **개체명목록** | 개체명의 출현 빈도를 확인할 때 사용합니다. 수정완료 결과의 재집계가 필요할 때 사용합니다. |
    """)

# 페이지 등록
pages = [
    st.Page(
        home,
        title="홈",
        icon="💁‍♀️",
        default=True,
    ),
    st.Page(
        "pages/2_dashboard.py",
        title="검수현황",
        icon="✍️",
    ),
    st.Page(
        "pages/6_entity_catalog.py",
        title="개체명목록",
        icon="📚",
    ),
    st.Page(
        "pages/1_ner.py",
        title="휴먼검수",
        icon="1️⃣",
    ),
    st.Page(
        "pages/3_martial_review.py",
        title="계엄기사",
        icon="2️⃣",
    ),
    st.Page(
        "pages/4_batch_review.py",
        title="일괄처리",
        icon="3️⃣",
    ),
    st.Page(
        "pages/5_unassigned_articles.py",
        title="샘플검수",
        icon="4️⃣",
    )
]

# 왼쪽 사이드바 메뉴 구성
navigation = st.navigation(pages, position="sidebar")
navigation.run()
