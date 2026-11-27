# -*- coding: utf-8 -*-
"""기사 목록의 필터와 위치를 위젯 수명과 별개로 보관한다."""
#---------------------------------------------------------------------------------------------------------
# 기본 설정 - 라이브러리 불러오기
#---------------------------------------------------------------------------------------------------------
import streamlit as st


#---------------------------------------------------------------------------------------------------------
# 기능 - 화면별 기사 목록 상태 조회 및 필터 복원
#---------------------------------------------------------------------------------------------------------
def get_article_list_state(scope):
    states = st.session_state.setdefault("article_list_states", {})
    state = states.setdefault(scope, {"filters": {}, "positions": {}})
    # 다른 화면에서 위젯이 제거되어도 마지막 필터로 목록을 복원한다.
    for key, value in state["filters"].items():
        if key not in st.session_state:
            st.session_state[key] = value
    return state


#---------------------------------------------------------------------------------------------------------
# 기능 - 기사 목록 필터 상태 보관
#---------------------------------------------------------------------------------------------------------
def remember_article_filters(state, keys):
    state["filters"].update({
        key: st.session_state[key]
        for key in keys if key in st.session_state
    })


#---------------------------------------------------------------------------------------------------------
# 화면 - 페이지별 기사 선택 복원 및 선택 목록 표시
#---------------------------------------------------------------------------------------------------------
def render_article_selector(article_ids, position, page, key):
    selections = position.setdefault("selections", {})
    selection = selections.get(page, {})
    saved_id = selection.get("doc_id")
    index = (
        article_ids.index(saved_id) if saved_id in article_ids
        else min(selection.get("index", 0), len(article_ids) - 1)
    )
    if st.session_state.get(key) not in article_ids:
        st.session_state[key] = article_ids[index]
    selected_id = st.radio(
        "기사 선택", article_ids, key=key,
        label_visibility="collapsed",
        on_change=lambda: position.update(active_doc_id=st.session_state[key], active_page=page),
    )
    position.update(active_doc_id=selected_id, active_page=page)
    selections[page] = {"doc_id": selected_id, "index": article_ids.index(selected_id)}
    return selected_id
