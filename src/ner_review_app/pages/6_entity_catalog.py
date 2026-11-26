"""대용량 개체명 목록 조회 및 완료된 기사 단위 재집계."""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ner_review_app.modules.entity_catalog import (
    catalog_ready,
    load_catalog_page,
    load_locations,
    load_pending_articles,
    prepare_catalog,
    refresh_article,
)
from src.ner_review_app.modules.postgredb import get_postgre_connect


@st.cache_data(ttl=3600, show_spinner=False)
def load_review_presses():
    with get_postgre_connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            rows = cursor.execute(
                """
                SELECT DISTINCT press FROM public.ner_human_review
                WHERE review_status = '완료' AND is_modified
                ORDER BY press
                """
            ).fetchall()
    return [row["press"] for row in rows]


st.title("개체명 목록")
st.caption("개체명 빈도와 출현 위치를 페이지 단위로 조회합니다. 완료된 수정 기사는 기사 단위로 목록에 반영할 수 있습니다.")
setup_message = st.session_state.pop("catalog_setup_message", None)
if setup_message:
    st.success(setup_message)

try:
    ready = catalog_ready()
except Exception as exc:
    st.error(f"개체명 목록 상태 조회 실패: {exc}")
    st.stop()

if not ready:
    st.info("대용량 목록 조회와 증분 재집계에 필요한 인덱스가 아직 준비되지 않았습니다.")
    setup_password = st.text_input("관리 비밀번호", type="password", key="catalog_setup_password")
    if st.button("개체명 목록 인덱스 준비"):
        try:
            with st.spinner("인덱스를 준비하고 있습니다. 데이터 규모에 따라 시간이 걸릴 수 있습니다."):
                prepare_catalog(setup_password)
            st.session_state["catalog_setup_message"] = "인덱스 준비가 끝났습니다."
            st.rerun()
        except Exception as exc:
            st.error(f"인덱스 준비 실패: {exc}")
    st.stop()

catalog_tab, refresh_tab = st.tabs(["개체명 조회", "수정완료 기사 재집계"])

with catalog_tab:
    exact_name = st.text_input("개체명 정확히 검색", placeholder="비워 두면 출현빈도 순으로 표시")
    if st.session_state.get("catalog_search") != exact_name:
        st.session_state["catalog_search"] = exact_name
        st.session_state["catalog_page_starts"] = [None]
    starts = st.session_state["catalog_page_starts"]
    try:
        rows = load_catalog_page(starts[-1], exact_name, 51)
        visible = rows[:50]
        st.caption(f"{len(starts)}페이지 · 현재 {len(visible)}개 개체명·분류")
        st.dataframe(
            pd.DataFrame(visible).rename(columns={
                "entity_name": "개체명", "entity_type": "분류", "mention_count": "출현빈도",
            }),
            hide_index=True,
            width="stretch",
        )
        if not exact_name:
            previous, following = st.columns(2)
            if previous.button("이전", key="catalog_previous", disabled=len(starts) == 1):
                starts.pop()
                st.rerun()
            if following.button("다음", key="catalog_next", disabled=len(rows) <= 50):
                last = visible[-1]
                starts.append((last["mention_count"], last["entity_name"], last["entity_type"]))
                st.rerun()

        if visible:
            selected = st.selectbox(
                "출현 위치를 볼 개체명",
                range(len(visible)),
                format_func=lambda i: f"{visible[i]['entity_name']} · {visible[i]['entity_type']} ({visible[i]['mention_count']:,})",
            )
            entity = visible[selected]
            entity_key = (entity["entity_name"], entity["entity_type"])
            if st.session_state.get("catalog_location_entity") != entity_key:
                st.session_state["catalog_location_entity"] = entity_key
                st.session_state["catalog_location_starts"] = [None]
            location_starts = st.session_state["catalog_location_starts"]
            locations = load_locations(*entity_key, location_starts[-1], 51)
            st.caption(f"출현 위치 {len(location_starts)}페이지")
            st.dataframe(
                pd.DataFrame(locations[:50]).rename(columns={
                    "press_id": "언론사", "file_id": "파일ID", "doc_id": "기사ID",
                    "paragraph_id": "문단ID", "sentence_id": "문장ID", "mention_count": "출현빈도",
                }),
                hide_index=True,
                width="stretch",
            )
            location_previous, location_next = st.columns(2)
            if location_previous.button("위치 이전", disabled=len(location_starts) == 1):
                location_starts.pop()
                st.rerun()
            if location_next.button("위치 다음", disabled=len(locations) <= 50):
                last = locations[49]
                location_starts.append((last["doc_id"], last["sentence_id"]))
                st.rerun()
    except Exception as exc:
        st.error(f"개체명 조회 실패: {exc}")

with refresh_tab:
    st.caption("완료 상태이며 수정된 문장만 원문 대신 적용합니다. 재집계는 선택한 기사 전체의 출현 목록·빈도·위치를 한 트랜잭션에서 갱신합니다.")
    refresh_message = st.session_state.pop("catalog_refresh_message", None)
    if refresh_message:
        st.success(refresh_message)
    try:
        presses = load_review_presses()
        if not presses:
            st.info("수정완료된 검수 문장이 없습니다.")
        else:
            press = st.selectbox("언론사", presses, key="catalog_review_press")
            pending = load_pending_articles(press)
            st.caption(f"최근 갱신 대기 {len(pending)}기사 표시 (한 번에 최대 25건)")
            st.dataframe(
                pd.DataFrame(pending).rename(columns={"doc_id": "기사ID", "changed_at": "수정완료 시각"}),
                hide_index=True,
                width="stretch",
            )
            doc_id = st.text_input("기사 ID 직접 지정", placeholder="재집계할 기사 ID")
            password = st.text_input("관리 비밀번호", type="password", key="catalog_refresh_password")
            single, batch = st.columns(2)
            if single.button("지정 기사 재집계", disabled=not doc_id.strip()):
                count = refresh_article(doc_id.strip(), password)
                st.session_state["catalog_refresh_message"] = f"{doc_id.strip()} · 개체명 출현 {count:,}건을 반영했습니다."
                st.rerun()
            if batch.button("대기 기사 25건 재집계", disabled=not pending):
                with st.spinner("대기 기사를 재집계하고 있습니다."):
                    for row in pending:
                        refresh_article(row["doc_id"], password)
                st.session_state["catalog_refresh_message"] = f"{len(pending)}기사 재집계를 마쳤습니다."
                st.rerun()
    except Exception as exc:
        st.error(f"개체명 재집계 실패: {exc}")
