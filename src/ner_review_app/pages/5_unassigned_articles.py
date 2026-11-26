"""검수 배정 대상에 없는 원본 기사를 표본 확인한다."""

import sys
import hashlib
import html
import re
from pathlib import Path

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ner_review_app.modules.postgredb import get_postgre_connect
from src.ner_review_app.modules.entity_catalog import catalog_ready, entity_search_pattern
from src.ner_review_app.modules.entity_filter import ENTITY_PAGE_SIZE, render_entity_filter
from src.ner_review_app.pages._article_list_state import (
    get_article_list_state, remember_article_filters, render_article_selector,
)


PAGE_SIZE = 20
TAG_PATTERN = re.compile(r"<\s*([^<>:]+?)\s*:\s*([^<>]+?)\s*>")


@st.cache_data(ttl=3600, show_spinner=False)
def load_presses():
    with get_postgre_connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            rows = cursor.execute(
                "SELECT DISTINCT publisher FROM public.ner_documents "
                "WHERE publisher IS NOT NULL ORDER BY publisher"
            ).fetchall()
    return [row["publisher"] for row in rows]


@st.cache_data(ttl=3600, show_spinner=False)
def load_entity_types():
    with get_postgre_connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '15s'")
            rows = cursor.execute(
                "SELECT DISTINCT entity_type FROM public.ner_entity_frequency ORDER BY entity_type"
            ).fetchall()
    return [row["entity_type"] for row in rows]


@st.cache_data(ttl=900, max_entries=64, show_spinner=False)
def load_entity_page(press, entity_type, entity_search="", frequent_first=True, after=None, article_search=""):
    """빈도표에서 현재 언론사의 배정 밖 기사에 있는 개체 쌍만 찾는다."""
    location_conditions = []
    conditions = []
    params = [press]
    document_condition = "publisher = %s"
    if article_search.strip():
        document_condition += " AND (doc_id ILIKE %s OR sentence_id ILIKE %s)"
        params.extend([f"%{article_search.strip()}%"] * 2)
    if entity_type:
        location_conditions.append("l.entity_type = %s")
        params.append(entity_type)
    if entity_search.strip():
        location_conditions.append("(l.entity_name ILIKE %s OR l.entity_type ILIKE %s)")
        params.extend([entity_search_pattern(entity_search)] * 2)
    direction = "DESC" if frequent_first else "ASC"
    if after is not None:
        comparison = "<" if frequent_first else ">"
        conditions.append(f"(f.mention_count, f.entity_name, f.entity_type) {comparison} (%s, %s, %s)")
        params.extend(after)
    params.append(ENTITY_PAGE_SIZE + 1)
    with get_postgre_connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '15s'")
            return cursor.execute(
                f"""
                WITH candidate_docs AS MATERIALIZED (
                    SELECT DISTINCT doc_id FROM public.ner_documents WHERE {document_condition}
                ), scoped_entities AS MATERIALIZED (
                    SELECT DISTINCT l.entity_name, l.entity_type
                    FROM candidate_docs c
                    JOIN public.ner_entity_location l ON l.doc_id = c.doc_id
                    WHERE NOT EXISTS (SELECT 1 FROM public.ner_human_review h WHERE h.doc_id = c.doc_id)
                      AND {" AND ".join(location_conditions) or "TRUE"}
                )
                SELECT f.entity_name, f.entity_type, f.mention_count
                FROM scoped_entities e
                JOIN public.ner_entity_frequency f USING (entity_name, entity_type)
                WHERE {" AND ".join(conditions) or "TRUE"}
                ORDER BY f.mention_count {direction}, f.entity_name {direction}, f.entity_type {direction}
                LIMIT %s
                """,
                params,
            ).fetchall()


@st.cache_data(ttl=600, max_entries=64, show_spinner=False)
def load_article_page(press, after_doc_id, entity_type=None, selected_entity=None, search_text=""):
    """기사·문장 ID 부분 검색과 개체 조건을 함께 적용해 기사 ID 순서로 조회한다."""
    document_conditions = ["d.publisher = %s", "d.doc_id > %s"]
    conditions = ["NOT EXISTS (SELECT 1 FROM public.ner_human_review h WHERE h.doc_id = c.doc_id)"]
    params = [press, after_doc_id]
    if search_text.strip():
        document_conditions.append("(d.doc_id ILIKE %s OR d.sentence_id ILIKE %s)")
        params.extend([f"%{search_text.strip()}%"] * 2)
    if entity_type or selected_entity:
        location_conditions = ["l.doc_id = c.doc_id"]
        if entity_type:
            location_conditions.append("l.entity_type = %s")
            params.append(entity_type)
        if selected_entity:
            location_conditions.extend(["l.entity_name = %s", "l.entity_type = %s"])
            params.extend(selected_entity)
        conditions.append(f"EXISTS (SELECT 1 FROM public.ner_entity_location l WHERE {' AND '.join(location_conditions)})")
    params.append(PAGE_SIZE + 1)
    with get_postgre_connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '15s'")
            rows = cursor.execute(
                f"""
                WITH candidates AS MATERIALIZED (
                    SELECT DISTINCT d.doc_id FROM public.ner_documents d
                    WHERE {" AND ".join(document_conditions)}
                )
                SELECT c.doc_id FROM candidates c
                WHERE {" AND ".join(conditions)}
                ORDER BY c.doc_id LIMIT %s
                """,
                params,
            ).fetchall()
    return rows[:PAGE_SIZE], len(rows) > PAGE_SIZE


def load_article(press, doc_id):
    # 본문은 캐시하지 않고 표시 시점에도 배정 밖 기사인지 확인한다.
    with get_postgre_connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            rows = cursor.execute(
                """
                SELECT d.paragraph_id, d.sentence_id, d.form
                FROM public.ner_documents d
                WHERE d.publisher = %s AND d.doc_id = %s
                  AND NOT EXISTS (
                      SELECT 1 FROM public.ner_human_review h
                      WHERE h.doc_id = d.doc_id
                  )
                ORDER BY d.sentence_id
                """,
                (press, doc_id),
            ).fetchall()
    return rows


def select_entity(press, entity_type, search_text):
    return render_entity_filter(
        (press, entity_type, search_text),
        lambda term, frequent_first, after: load_entity_page(press, entity_type, term, frequent_first, after, search_text),
        "unassigned_entity",
    )


def highlighted_form(form, entity_type=None, selected_entity=None):
    """원문을 HTML 이스케이프한 뒤 태그와 선택한 개체만 강조한다."""
    parts = []
    previous = 0
    for tag in TAG_PATTERN.finditer(form):
        parts.append(html.escape(form[previous:tag.start()]))
        pair = (tag[1].strip(), tag[2].strip())
        selected = pair == selected_entity if selected_entity else entity_type == pair[1]
        style = "background:#fef08a;color:#713f12;font-weight:600" if selected else "background:#f1f5f9;color:#334155"
        parts.append(f'<span style="{style};padding:2px 4px;border-radius:4px">{html.escape(tag[0])}</span>')
        previous = tag.end()
    parts.append(html.escape(form[previous:]))
    return '<div style="white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.95;font-size:16px">' + "".join(parts) + '</div>'


st.caption("검수 대상 외 기사 (조회용)")
article_state = get_article_list_state(("sample",))

try:
    presses = load_presses()
    if not presses:
        st.info("원본 기사가 없습니다.")
        st.stop()
    search_text = st.sidebar.text_input(
        "기사ID 또는 문장ID 검색", placeholder="기사ID 또는 문장ID 검색",
        key="unassigned_search_text", label_visibility="collapsed",
    ).strip()
    if st.session_state.get("unassigned_press") not in presses:
        st.session_state["unassigned_press"] = presses[0]
    with st.sidebar.popover(f"언론사 ({st.session_state.unassigned_press})", width="stretch"):
        press = st.radio("언론사 선택", presses, key="unassigned_press", label_visibility="collapsed")
    entity_type = None
    priority_entity = None
    try:
        if catalog_ready():
            type_options = [None, *load_entity_types()]
            if st.session_state.get("unassigned_entity_type") not in type_options:
                st.session_state["unassigned_entity_type"] = None
            type_label = st.session_state.get("unassigned_entity_type") or "전체"
            with st.sidebar.popover(f"분류 ({type_label})", width="stretch"):
                entity_type = st.radio(
                    "분류 선택", type_options, format_func=lambda value: value or "전체",
                    key="unassigned_entity_type", label_visibility="collapsed",
                )
        priority_entity = select_entity(press, entity_type, search_text)
    except Exception:
        st.sidebar.warning("개체명 목록 상태를 확인하지 못했습니다. 언론사와 기사 ID로 조회할 수 있습니다.")
    selected_entity = (priority_entity["entity_name"], priority_entity["entity_type"]) if priority_entity else None
    remember_article_filters(article_state, [
        "unassigned_search_text", "unassigned_press", "unassigned_entity_type",
        "unassigned_entity_enabled", "unassigned_entity_name", "unassigned_entity_order",
    ])
    filter_key = (press, entity_type, selected_entity, search_text)
    position = article_state["positions"].setdefault(filter_key, {"starts": [""]})
    starts = position["starts"]
    st.html("""
        <style>
        [data-testid="stSidebar"] [data-testid="stPopover"] > button {
            background-color:white; border:1px solid #e0e0e0; border-radius:8px;
            min-height:44px; padding:0 12px; color:#31333f; font-size:14px; font-weight:400;
        }
        .st-key-unassigned_articles [role="radiogroup"] {gap:1px;}
        .st-key-unassigned_articles [role="radiogroup"] label {
            padding-top:2px; padding-bottom:2px; min-height:26px;
        }
        .st-key-unassigned_articles [data-testid="stButton"] button {
            min-height:30px; padding:0 4px; border-radius:6px; color:#334155;
        }
        </style>
    """)
    with st.sidebar.container(key="unassigned_articles"):
        title_col, refresh_col = st.columns([4, 1], vertical_alignment="center")
        title_col.markdown("**기사 목록**")
        if refresh_col.button("", icon=":material/refresh:", help="목록 새로고침", key="unassigned_refresh"):
            load_article_page.clear()
            load_entity_page.clear()
            st.rerun()
        page_rows, has_next = load_article_page(press, starts[-1], entity_type, selected_entity, search_text)
        article_ids = [row["doc_id"] for row in page_rows]
        selected_doc_id = None
        if article_ids:
            selection_key = "unassigned_article_" + hashlib.md5(repr((filter_key, starts[-1])).encode("utf-8")).hexdigest()
            selected_doc_id = render_article_selector(article_ids, position, starts[-1], selection_key)
        elif len(starts) > 1:
            starts.pop()
            st.rerun()
        previous, page_col, following = st.columns([0.5, 2, 0.5])
        if previous.button("‹", key="unassigned_article_previous", help="이전 페이지", disabled=len(starts) == 1, width="stretch"):
            starts.pop()
            st.rerun()
        first = (len(starts) - 1) * PAGE_SIZE + 1
        last = first + len(article_ids) - 1
        page_col.markdown(
            f'<div style="text-align:center;font-size:12px;color:#64748b;padding-top:7px;white-space:nowrap">'
            f'{len(starts)} 페이지 <span style="color:#94a3b8">({f"{first:,}–{last:,}" if article_ids else "0"})</span></div>',
            unsafe_allow_html=True,
        )
        if following.button("›", key="unassigned_article_next", help="다음 페이지", disabled=not has_next, width="stretch"):
            starts.append(article_ids[-1])
            st.rerun()
    if selected_doc_id is None:
        st.info("조건에 맞는 기사가 없습니다.")
        st.stop()
    sentences = load_article(press, selected_doc_id)
    if not sentences:
        st.info("이 기사는 현재 검수 대상에 포함되어 있습니다. 목록을 새로고침해 주세요.")
        st.stop()
    sentences.sort(key=lambda row: tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in row["sentence_id"].split(".")
    ))
    st.markdown("### 기사 본문")
    st.caption(f"{selected_doc_id} · {len(sentences):,}문장 · 조회 전용")
    if selected_entity:
        st.caption(f"강조: {selected_entity[0]} · {selected_entity[1]} · 전체 출현 {priority_entity['mention_count']:,}회")
    elif entity_type:
        st.caption(f"강조: {entity_type} 분류의 개체")
    for index, row in enumerate(sentences, start=1):
        with st.container(border=True):
            st.caption(f"문장 {index:02d} · {row['sentence_id']}")
            st.markdown(highlighted_form(row["form"], entity_type, selected_entity), unsafe_allow_html=True)
except Exception as exc:
    st.error(f"기사 조회 실패: {exc}")
