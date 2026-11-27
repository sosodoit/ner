# -*- coding: utf-8 -*-
"""검수 대상 외 원본 기사 조회용"""
#---------------------------------------------------------------------------------------------------------
# 기본 설정 - 라이브러리 불러오기
#---------------------------------------------------------------------------------------------------------
import re
import sys
import html
import hashlib
import streamlit as st
from pathlib import Path

#---------------------------------------------------------------------------------------------------------
# 기본 설정 - 프로젝트 경로 및 모듈 불러오기
#---------------------------------------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ner_review_app.modules.postgredb import get_postgre_connect
from src.ner_review_app.modules.entity_filter import ENTITY_PAGE_SIZE, render_entity_filter
from src.ner_review_app.modules.entity_catalog import entity_search_pattern
from src.ner_review_app.modules.entity_tags import ENTITY_TAG_PATTERN
from src.ner_review_app.modules._article_list_state import get_article_list_state, remember_article_filters, render_article_selector


#---------------------------------------------------------------------------------------------------------
# 기본 설정 - 페이지 크기 및 개체 태그 패턴
#---------------------------------------------------------------------------------------------------------
PAGE_SIZE = 10
TAG_PATTERN = re.compile(ENTITY_TAG_PATTERN)


#---------------------------------------------------------------------------------------------------------
# 기능 - 원본 기사 언론사 조회
#---------------------------------------------------------------------------------------------------------
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


#---------------------------------------------------------------------------------------------------------
# 기능 - 배정 밖 기사의 개체 목록 조회
#---------------------------------------------------------------------------------------------------------
def sample_search_conditions(search_text):
    """넓은 ID 검색은 기사 색인, 구체적인 부분 검색은 GIN 색인으로 조회한다."""
    text = search_text.strip()
    if not text:
        return "TRUE", "TRUE", []
    pattern = f"%{text}%"
    sentence_id = re.fullmatch(r"([A-Za-z]+\d+\.\d+)(?:\.\d+)+", text)
    if sentence_id:
        # 문장 ID의 앞 두 구간은 기사 ID이므로, 해당 기사 안에서만 부분 검색한다.
        return """(d.doc_id ILIKE %s AND
            (d.doc_id ILIKE %s OR d.sentence_id ILIKE %s))""", "TRUE", [sentence_id[1], pattern, pattern]
    article_id = re.fullmatch(r"[A-Za-z]+\d+\.(\d+)(?:\.\d+)*", text)
    broad_search = (
        len(text) < 4
        or (article_id is not None and len(article_id[1]) < 4)
        or re.fullmatch(r"[A-Za-z]+\d*", text) is not None
    )
    if broad_search:
        # 기사 ID 비교로 먼저 찾고, 필요한 기사만 기본키 색인으로 문장 ID를 확인한다.
        # OFFSET 0은 전체 문장 테이블을 읽는 해시 서브쿼리로의 변환을 막는다.
        condition = """(c.doc_id ILIKE %s OR EXISTS (
            SELECT 1 FROM public.ner_documents search_sentence
            WHERE search_sentence.doc_id = c.doc_id AND search_sentence.sentence_id ILIKE %s
            OFFSET 0
        ))"""
        return "TRUE", condition, [pattern, pattern]
    return "(d.doc_id ILIKE %s OR d.sentence_id ILIKE %s)", "TRUE", [pattern, pattern]


@st.cache_data(ttl=900, max_entries=64, show_spinner=False)
def load_entity_page(press, entity_type, entity_search="", frequent_first=True, after=None, article_search=""):
    """빈도표에서 현재 언론사의 배정 밖 기사에 있는 개체 쌍만 찾는다."""
    location_conditions = []
    conditions = []
    document_search, article_condition, search_params = sample_search_conditions(article_search)
    params = [press, *search_params]
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
    article_ctes = f"""
        candidate_docs AS NOT MATERIALIZED (
            SELECT DISTINCT d.doc_id FROM public.ner_documents d
            WHERE d.publisher = %s AND {document_search}
        ), sample_docs AS MATERIALIZED (
            SELECT c.doc_id FROM candidate_docs c
            WHERE NOT EXISTS (SELECT 1 FROM public.ner_human_review h WHERE h.doc_id = c.doc_id)
              AND {article_condition}
        )
    """
    if document_search == "TRUE":
        # 후보 기사가 많으면 모든 출현 위치를 합쳐 정렬하지 않고, 빈도순으로
        # 개체를 읽으며 대상 기사에 출현하는지 확인해 한 페이지에서 멈춘다.
        query = f"""
            WITH {article_ctes}
            SELECT f.entity_name, f.entity_type, f.mention_count
            FROM public.ner_entity_frequency f
            WHERE {" AND ".join(location_conditions).replace('l.', 'f.') or "TRUE"}
              AND {" AND ".join(conditions) or "TRUE"}
              AND EXISTS (SELECT 1 FROM sample_docs)
              AND EXISTS (
                  SELECT 1 FROM public.ner_entity_location l
                  WHERE l.entity_name = f.entity_name AND l.entity_type = f.entity_type
                    AND l.doc_id IN (SELECT doc_id FROM sample_docs)
                  OFFSET 0
              )
            ORDER BY f.mention_count {direction}, f.entity_name {direction}, f.entity_type {direction}
            LIMIT %s
        """
    else:
        query = f"""
            WITH {article_ctes}, scoped_entities AS MATERIALIZED (
                SELECT DISTINCT l.entity_name, l.entity_type
                FROM sample_docs c
                JOIN public.ner_entity_location l ON l.doc_id = c.doc_id
                WHERE {" AND ".join(location_conditions) or "TRUE"}
            )
            SELECT f.entity_name, f.entity_type, f.mention_count
            FROM scoped_entities e
            JOIN public.ner_entity_frequency f USING (entity_name, entity_type)
            WHERE {" AND ".join(conditions) or "TRUE"}
            ORDER BY f.mention_count {direction}, f.entity_name {direction}, f.entity_type {direction}
            LIMIT %s
        """
    with get_postgre_connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '15s'")
            return cursor.execute(query, params).fetchall()


#---------------------------------------------------------------------------------------------------------
# 기능 - 검색 및 개체 조건별 기사 목록 조회
#---------------------------------------------------------------------------------------------------------
@st.cache_data(ttl=600, max_entries=64, show_spinner=False)
def load_article_page(press, after_doc_id, entity_type=None, selected_entity=None, search_text=""):
    """기사·문장 ID 부분 검색과 개체 조건을 함께 적용해 기사 ID 순서로 조회한다."""
    # 부분 검색에는 ner_document_search_indexes.sql의 GIN 인덱스를 사용한다.
    # 후보를 강제 구체화하지 않아 첫 페이지의 LIMIT까지 인덱스 조회를 유지한다.
    document_conditions = ["d.publisher = %s", "d.doc_id > %s"]
    conditions = ["NOT EXISTS (SELECT 1 FROM public.ner_human_review h WHERE h.doc_id = c.doc_id)"]
    document_search, article_condition, search_params = sample_search_conditions(search_text)
    document_conditions.append(document_search)
    conditions.append(article_condition)
    params = [press, after_doc_id, *search_params]
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
                WITH candidates AS NOT MATERIALIZED (
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


#---------------------------------------------------------------------------------------------------------
# 기능 - 배정 여부 확인 및 기사 본문 조회
#---------------------------------------------------------------------------------------------------------
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


#---------------------------------------------------------------------------------------------------------
# 기능 - 개체 선택 필터 표시
#---------------------------------------------------------------------------------------------------------
def select_entity(press, entity_type, search_text):
    return render_entity_filter(
        (press, entity_type, search_text),
        lambda term, frequent_first, after: load_entity_page(press, entity_type, term, frequent_first, after, search_text),
        "unassigned_entity",
        inline_results=True,
    )


#---------------------------------------------------------------------------------------------------------
# 기능 - 본문 개체 태그 및 선택 개체 강조
#---------------------------------------------------------------------------------------------------------
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


#---------------------------------------------------------------------------------------------------------
# 상단 - 조회 안내 및 기사 목록 상태 초기화
#---------------------------------------------------------------------------------------------------------
with st.container(border=True):
    st.markdown("**원본 기사 조회**")
    st.caption("검수 대상 외의 원본 기사를 조회합니다.")
article_state = get_article_list_state(("sample",))

#---------------------------------------------------------------------------------------------------------
# 사이드바 - 언론사 및 기사 검색 조건
#---------------------------------------------------------------------------------------------------------
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
    #---------------------------------------------------------------------------------------------------------
    # 사이드바 - 우선 조회 개체 선택
    #---------------------------------------------------------------------------------------------------------
    entity_type = None
    priority_entity = None
    try:
        priority_entity = select_entity(press, entity_type, search_text)
    except Exception:
        st.sidebar.warning("개체명 목록 상태를 확인하지 못했습니다. 언론사와 기사 ID로 조회할 수 있습니다.")
    selected_entity = (priority_entity["entity_name"], priority_entity["entity_type"]) if priority_entity else None
    #---------------------------------------------------------------------------------------------------------
    # 사이드바 - 조회 조건 및 페이지 위치 유지
    #---------------------------------------------------------------------------------------------------------
    remember_article_filters(article_state, [
        "unassigned_search_text", "unassigned_press",
        "unassigned_entity_enabled", "unassigned_entity_name", "unassigned_entity_order",
    ])
    filter_key = (press, entity_type, selected_entity, search_text)
    position = article_state["positions"].setdefault(filter_key, {"starts": [""]})
    starts = position["starts"]
    #---------------------------------------------------------------------------------------------------------
    # 화면 설정 - 사이드바 필터 및 기사 목록 서식
    #---------------------------------------------------------------------------------------------------------
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
    #---------------------------------------------------------------------------------------------------------
    # 사이드바 - 기사 목록 조회
    #---------------------------------------------------------------------------------------------------------
    with st.sidebar.container(key="unassigned_articles"):
        st.markdown("**기사 목록**")
        page_rows, has_next = load_article_page(press, starts[-1], entity_type, selected_entity, search_text)
        article_ids = [row["doc_id"] for row in page_rows]
        #---------------------------------------------------------------------------------------------------------
        # 사이드바 - 조회할 기사 선택
        #---------------------------------------------------------------------------------------------------------
        selected_doc_id = None
        if article_ids:
            selection_key = "unassigned_article_" + hashlib.md5(repr((filter_key, starts[-1])).encode("utf-8")).hexdigest()
            selected_doc_id = render_article_selector(article_ids, position, starts[-1], selection_key)
        elif len(starts) > 1:
            starts.pop()
            st.rerun()
        #---------------------------------------------------------------------------------------------------------
        # 사이드바 - 기사 목록 페이지 이동
        #---------------------------------------------------------------------------------------------------------
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
    #---------------------------------------------------------------------------------------------------------
    # 본문 - 선택 기사 및 배정 밖 여부 확인
    #---------------------------------------------------------------------------------------------------------
    if selected_doc_id is None:
        st.info("조건에 맞는 기사가 없습니다.")
        st.stop()
    sentences = load_article(press, selected_doc_id)
    if not sentences:
        load_article_page.clear()
        load_entity_page.clear()
        st.rerun()
    #---------------------------------------------------------------------------------------------------------
    # 본문 - 문장 순서 정렬 및 기사 정보 표시
    #---------------------------------------------------------------------------------------------------------
    sentences.sort(key=lambda row: tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in row["sentence_id"].split(".")
    ))
    st.info(f"{selected_doc_id} ({len(sentences):,}문장)")
    if selected_entity:
        st.info(f"강조: {selected_entity[0]} · {selected_entity[1]} · 전체 출현 {priority_entity['mention_count']:,}회")
    elif entity_type:
        st.info(f"강조: {entity_type} 분류의 개체")
    #---------------------------------------------------------------------------------------------------------
    # 본문 - 문장별 개체 강조 표시
    #---------------------------------------------------------------------------------------------------------
    with st.container(border=True):
        for index, row in enumerate(sentences, start=1):
            if index > 1:
                st.markdown(
                    '<hr style="margin:8px 0; border:none; border-top:1px solid #e5e7eb;">',
                    unsafe_allow_html=True,
                )

            st.markdown(
                f'<div style="font-size:12px; color:#8b9099;">'
                f'<strong>문장 {index:02d}</strong> · {row["sentence_id"]}'
                f'</div>'
                f'{highlighted_form(row["form"], entity_type, selected_entity)}',
                unsafe_allow_html=True,
            )
except Exception as exc:
    st.error(f"기사 조회 실패: {exc}")
