# -*- coding: utf-8 -*-
"""대용량 개체명 목록 조회 및 완료된 기사 단위 재집계"""
#---------------------------------------------------------------------------------------------------------
# 기본 설정 - 라이브러리 불러오기
#---------------------------------------------------------------------------------------------------------
import sys
import pandas as pd
import streamlit as st
from pathlib import Path

#---------------------------------------------------------------------------------------------------------
# 기본 설정 - 프로젝트 경로 및 모듈 불러오기
#---------------------------------------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ner_review_app.modules.entity_catalog import (
    catalog_ready,
    check_admin_password,
    load_catalog_page,
    load_locations,
    load_pending_articles,
    prepare_catalog,
    refresh_article,
)
from src.ner_review_app.modules.postgredb import get_postgre_connect


#---------------------------------------------------------------------------------------------------------
# 기능 - 수정완료 기사의 언론사 조회
#---------------------------------------------------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def load_review_presses():
    with get_postgre_connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            rows = cursor.execute(
                """
                SELECT DISTINCT press FROM public.ner_human_review
                WHERE review_status = '완료' AND is_modified
                UNION
                SELECT DISTINCT press FROM public.ner_human_review_add
                WHERE review_status = '완료' AND is_modified
                ORDER BY press
                """
            ).fetchall()
    return [row["press"] for row in rows]


#---------------------------------------------------------------------------------------------------------
# 상단 - 개체명 목록 안내 및 준비 결과 표시
#---------------------------------------------------------------------------------------------------------
with st.container(border=True):
    st.markdown("**개체명 목록**")
    st.caption("개체명 빈도와 출현 위치를 페이지 단위로 조회합니다.")
setup_message = st.session_state.pop("catalog_setup_message", None)
if setup_message:
    st.success(setup_message)

#---------------------------------------------------------------------------------------------------------
# 기본 설정 - 개체명 목록 준비 상태 확인
#---------------------------------------------------------------------------------------------------------
try:
    ready = catalog_ready()
except Exception as exc:
    st.error(f"개체명 목록 상태 조회 실패: {exc}")
    st.stop()

#---------------------------------------------------------------------------------------------------------
# 기본 설정 - 개체명 목록 인덱스 준비
#---------------------------------------------------------------------------------------------------------
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

#---------------------------------------------------------------------------------------------------------
# 본문 - 탭 구성
#---------------------------------------------------------------------------------------------------------
catalog_tab, refresh_tab = st.tabs(["개체명 조회", "수정완료 기사 재집계"])

with catalog_tab:
    #---------------------------------------------------------------------------------------------------------
    # 개체명 조회 - 검색 조건 및 페이지 초기화
    #---------------------------------------------------------------------------------------------------------
    entity_search = st.text_input("개체명 · 분류 검색", placeholder="개체명 또는 분류의 일부 입력").strip()
    entity_type = st.selectbox("분류", ["전체", "PS", "LC", "OG", "AF", "DT", "EV"])
    if (
        st.session_state.get("catalog_search") != entity_search
        or st.session_state.get("catalog_entity_type") != entity_type
    ):
        st.session_state["catalog_search"] = entity_search
        st.session_state["catalog_entity_type"] = entity_type
        st.session_state["catalog_page_starts"] = [None]
    starts = st.session_state["catalog_page_starts"]
    #---------------------------------------------------------------------------------------------------------
    # 개체명 조회 - 출현빈도 목록 표시
    #---------------------------------------------------------------------------------------------------------
    try:
        rows = load_catalog_page(
            starts[-1], entity_search, 51,
            entity_type=None if entity_type == "전체" else entity_type,
        )
        visible = rows[:50]
        st.dataframe(
            pd.DataFrame(visible).rename(columns={
                "entity_name": "개체명", "entity_type": "분류", "mention_count": "출현빈도",
            }),
            hide_index=True,
            width="stretch",
        )
        #---------------------------------------------------------------------------------------------------------
        # 개체명 조회 - 목록 페이지 이동
        #---------------------------------------------------------------------------------------------------------
        previous, following = st.columns(2)
        if previous.button("이전", key="catalog_previous", disabled=len(starts) == 1):
            starts.pop()
            st.rerun()
        with following.container(horizontal=True, horizontal_alignment="right"):
            if st.button("다음", key="catalog_next", disabled=len(rows) <= 50):
                last = visible[-1]
                starts.append((last["mention_count"], last["entity_name"], last["entity_type"]))
                st.rerun()

        #---------------------------------------------------------------------------------------------------------
        # 개체명 조회 - 출현 위치 대상 선택
        #---------------------------------------------------------------------------------------------------------
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
            #---------------------------------------------------------------------------------------------------------
            # 개체명 조회 - 출현 위치 목록 표시
            #---------------------------------------------------------------------------------------------------------
            locations = load_locations(*entity_key, location_starts[-1], 51)
            # st.caption(f"출현 위치 {len(location_starts)}페이지")
            st.dataframe(
                pd.DataFrame(locations[:50]).rename(columns={
                    "press_id": "언론사", "file_id": "파일ID", "doc_id": "기사ID",
                    "paragraph_id": "문단ID", "sentence_id": "문장ID", "mention_count": "출현빈도",
                }),
                hide_index=True,
                width="stretch",
            )
            #---------------------------------------------------------------------------------------------------------
            # 개체명 조회 - 출현 위치 페이지 이동
            #---------------------------------------------------------------------------------------------------------
            location_previous, location_next = st.columns(2)
            if location_previous.button("이전", disabled=len(location_starts) == 1):
                location_starts.pop()
                st.rerun()
            with location_next.container(horizontal=True, horizontal_alignment="right"):
                if st.button("다음", disabled=len(locations) <= 50):
                    last = locations[49]
                    location_starts.append((last["doc_id"], last["sentence_id"]))
                    st.rerun()
    except Exception as exc:
        st.error(f"개체명 조회 실패: {exc}")

with refresh_tab:
    #---------------------------------------------------------------------------------------------------------
    # 기사 재집계 - 처리 기준 안내 및 이전 결과 표시
    #---------------------------------------------------------------------------------------------------------
    st.caption("수정 완료 상태의 문장을 기사 전체의 출현 목록·빈도·위치를 한 트랜잭션에서 갱신합니다.")
    refresh_message = st.session_state.pop("catalog_refresh_message", None)
    if refresh_message:
        st.success(refresh_message)
    batch_result = st.session_state.pop("catalog_batch_result", None)
    if batch_result:
        if batch_result["completed"]:
            st.success(f"{batch_result['completed']:,}기사 재집계를 마쳤습니다.")
        if batch_result["failures"]:
            st.warning(f"{len(batch_result['failures']):,}기사는 재집계하지 못했습니다. 성공한 기사는 반영되었으며, 실패한 기사는 대기 대상으로 남습니다.")
            st.dataframe(pd.DataFrame(batch_result["failures"]), hide_index=True, width="stretch")
    #---------------------------------------------------------------------------------------------------------
    # 기사 재집계 - 언론사 및 처리 건수 선택
    #---------------------------------------------------------------------------------------------------------
    try:
        presses = load_review_presses()
        if not presses:
            st.info("수정완료된 검수 문장이 없습니다.")
        else:
            press = st.selectbox("언론사", presses, key="catalog_review_press")
            batch_size = st.selectbox(
                "한 번에 처리할 기사 수", [50, 100, 250, 500], index=1,
                key="catalog_refresh_batch_size", format_func=lambda value: f"{value:,}건",
            )
            #---------------------------------------------------------------------------------------------------------
            # 기사 재집계 - 대기 기사 목록 조회 및 표시
            #---------------------------------------------------------------------------------------------------------
            pending = load_pending_articles(press, batch_size)
            st.caption(f"이번 처리 대상 {len(pending):,}기사 · 최근 수정된 기사부터 최대 {batch_size:,}건 조회")
            st.caption("기사별로 처리 결과를 저장합니다. 일괄처리 후 남은 대상을 이어서 처리할 수 있습니다.")
            st.dataframe(
                pd.DataFrame(pending).rename(columns={"doc_id": "기사ID", "changed_at": "수정완료 시각"}),
                hide_index=True,
                width="stretch",
            )
            #---------------------------------------------------------------------------------------------------------
            # 기사 재집계 - 관리자 확인 및 일괄 재집계
            #---------------------------------------------------------------------------------------------------------
            password_col, batch_button_col = st.columns([4, 2], vertical_alignment="bottom")
            with password_col:
                password = st.text_input("관리 비밀번호", type="password", key="catalog_refresh_password")
            with batch_button_col:
                batch_refresh_clicked = st.button(
                    f"대기 기사 {len(pending):,}건 일괄 재집계",
                    disabled=not pending, type="primary", width="stretch",
                )
            if batch_refresh_clicked:
                if not check_admin_password(password):
                    st.error("관리 비밀번호가 올바르지 않습니다.")
                else:
                    completed = 0
                    failures = []
                    progress = st.progress(0.0, text=f"0 / {len(pending):,}기사 처리")
                    for index, row in enumerate(pending, start=1):
                        try:
                            refresh_article(row["doc_id"], password)
                            completed += 1
                        except Exception as exc:
                            failures.append({"기사ID": row["doc_id"], "실패 사유": str(exc)})
                        progress.progress(index / len(pending), text=f"{index:,} / {len(pending):,}기사 처리")
                    st.session_state["catalog_batch_result"] = {"completed": completed, "failures": failures}
                    st.rerun()
            #---------------------------------------------------------------------------------------------------------
            # 기사 재집계 - 기사 ID 지정 재처리
            #---------------------------------------------------------------------------------------------------------
            st.divider()
            st.markdown("**특정 기사 재처리**")
            article_col, article_button_col = st.columns([4, 2], vertical_alignment="bottom")
            with article_col:
                doc_id = st.text_input("기사 ID 직접 지정", placeholder="기사 ID 직접 지정", label_visibility="collapsed")
            with article_button_col:
                article_refresh_clicked = st.button(
                    "지정 기사 재집계", disabled=not doc_id.strip(),
                    type="primary", width="stretch",
                )
            if article_refresh_clicked:
                count = refresh_article(doc_id.strip(), password)
                st.session_state["catalog_refresh_message"] = f"{doc_id.strip()} · 개체명 출현 {count:,}건을 반영했습니다."
                st.rerun()
    except Exception as exc:
        st.error(f"개체명 재집계 실패: {exc}")
