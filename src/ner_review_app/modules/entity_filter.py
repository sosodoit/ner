"""검수 화면들이 공유하는 개체 목록 조회·선택 영역."""
import hashlib

import streamlit as st

from src.ner_review_app.modules.entity_catalog import catalog_ready


ENTITY_PAGE_SIZE = 30


def render_entity_filter(scope, load_page, key_prefix, inline_results=False):
    if st.session_state.get(f"{key_prefix}_scope") != scope:
        st.session_state[f"{key_prefix}_scope"] = scope
        st.session_state[f"{key_prefix}_selected"] = None
        st.session_state[f"{key_prefix}_query"] = None
        st.session_state[f"{key_prefix}_starts"] = [None]
    if f"{key_prefix}_query" not in st.session_state:
        st.session_state[f"{key_prefix}_query"] = None
    if not st.sidebar.checkbox("개체명 목록 기준 검수", key=f"{key_prefix}_enabled"):
        st.session_state[f"{key_prefix}_selected"] = None
        st.session_state[f"{key_prefix}_query"] = None
        st.session_state[f"{key_prefix}_starts"] = [None]
        return None

    root_key = f"{key_prefix}_filter"
    st.html(f"""
        <style>
        .st-key-{root_key} [data-testid="stTextInput"] [data-baseweb="input"],
        .st-key-{root_key} [data-testid="stSelectbox"] [data-baseweb="select"] > div,
        .st-key-{root_key} [data-testid="stFormSubmitButton"] button,
        .st-key-{root_key} [data-testid="stButton"] button {{
            height:44px !important; min-height:44px !important;
            border:1px solid #c5c8ce !important; border-radius:8px !important;
            box-sizing:border-box;
        }}
        .st-key-{root_key} [data-testid="stRadio"] [role="radiogroup"] {{
            column-gap:24px !important; margin:0 !important; padding:0 !important;
        }}
        </style>
    """)
    with st.sidebar.container(key=root_key):
        try:
            ready = catalog_ready()
        except Exception:
            st.warning("개체명 목록 상태를 확인하지 못했습니다. 잠시 후 다시 조회해 주세요.")
            return st.session_state[f"{key_prefix}_selected"]
        if not ready:
            st.info("개체명목록 화면에서 초기 준비를 완료한 뒤 사용할 수 있습니다.")
            return None
        with st.form(f"{key_prefix}_search", border=not inline_results):
            term = st.text_input(
                "개체명·분류 검색", placeholder="개체명 또는 분류의 일부 입력",
                key=f"{key_prefix}_name",
            ).strip()
            order = st.radio(
                "출현빈도정렬", ["많은 순", "적은 순"], horizontal=True,
                key=f"{key_prefix}_order",
            )
            if st.form_submit_button("개체 목록 조회", width="stretch"):
                st.session_state[f"{key_prefix}_query"] = (term, order)
                st.session_state[f"{key_prefix}_starts"] = [None]

        query = st.session_state[f"{key_prefix}_query"]
        if query is not None:
            starts = st.session_state[f"{key_prefix}_starts"]
            with st.container(border=not inline_results):
                if not inline_results:
                    st.markdown("**조회 결과에서 개체 선택**")
                try:
                    rows = load_page(query[0], query[1] == "많은 순", starts[-1])
                    visible = rows[:ENTITY_PAGE_SIZE]
                    if visible:
                        entities = {(row["entity_name"], row["entity_type"]): row for row in visible}
                        choice_key = f"{key_prefix}_choice_" + hashlib.md5(
                            repr((scope, query, starts[-1])).encode("utf-8")
                        ).hexdigest()
                        choice = st.selectbox(
                            "검수할 개체명·분류", list(entities), key=choice_key,
                            format_func=lambda pair: f"{pair[0]} · {pair[1]} · 전체 {entities[pair]['mention_count']:,}회",
                            label_visibility="collapsed" if inline_results else "visible",
                        )
                        if st.button("선택 개체로 조회", key=f"{key_prefix}_apply", width="stretch"):
                            st.session_state[f"{key_prefix}_selected"] = entities[choice]
                    else:
                        st.info("조건에 맞는 개체가 없습니다.")
                    previous, following = st.columns(2, gap="small")
                    if previous.button("개체 이전", key=f"{key_prefix}_previous", disabled=len(starts) == 1, width="stretch"):
                        starts.pop()
                        st.rerun()
                    if following.button("개체 다음", key=f"{key_prefix}_next", disabled=len(rows) <= ENTITY_PAGE_SIZE, width="stretch"):
                        last = visible[-1]
                        starts.append((last["mention_count"], last["entity_name"], last["entity_type"]))
                        st.rerun()
                except Exception:
                    st.warning("개체 목록을 불러오지 못했습니다. 검색어를 더 구체적으로 입력해 주세요.")

        selected = st.session_state[f"{key_prefix}_selected"]
        if selected:
            st.caption(f"적용 중: {selected['entity_name']} · {selected['entity_type']} · 전체 {selected['mention_count']:,}회")
            if st.button("개체 선택 해제", key=f"{key_prefix}_clear", width="stretch"):
                st.session_state[f"{key_prefix}_selected"] = None
                st.rerun()
    return st.session_state[f"{key_prefix}_selected"]
