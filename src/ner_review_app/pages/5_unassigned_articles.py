"""검수 배정 대상에 없는 원본 기사를 표본 확인한다."""

import sys
from pathlib import Path

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ner_review_app.modules.postgredb import get_postgre_connect


PAGE_SIZE = 20
SCAN_SIZE = 200


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


@st.cache_data(ttl=600, show_spinner=False)
def load_article_page(press, after_doc_id):
    """원문 인덱스로 작은 구간만 훑고 배정된 기사 ID를 제외한다."""
    articles = []
    cursor_doc_id = after_doc_id
    with get_postgre_connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            while len(articles) < PAGE_SIZE + 1:
                rows = cursor.execute(
                    """
                    WITH candidates AS MATERIALIZED (
                        SELECT DISTINCT ON (doc_id)
                            doc_id, document_title, date, topic
                        FROM public.ner_documents
                        WHERE publisher = %s AND doc_id > %s
                        ORDER BY doc_id, sentence_id
                        LIMIT %s
                    )
                    SELECT c.*,
                           NOT EXISTS (
                               SELECT 1 FROM public.ner_human_review h
                               WHERE h.doc_id = c.doc_id
                           ) AS unassigned
                    FROM candidates c ORDER BY c.doc_id
                    """,
                    (press, cursor_doc_id, SCAN_SIZE),
                ).fetchall()
                if not rows:
                    break
                cursor_doc_id = rows[-1]["doc_id"]
                articles.extend(row for row in rows if row["unassigned"])
                if len(rows) < SCAN_SIZE:
                    break
    return articles[:PAGE_SIZE], len(articles) > PAGE_SIZE


@st.cache_data(ttl=600, show_spinner=False)
def load_article(doc_id):
    with get_postgre_connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            rows = cursor.execute(
                """
                SELECT d.paragraph_id, d.sentence_id, d.form,
                       d.document_title, d.publisher, d.date, d.topic
                FROM public.ner_documents d
                WHERE d.doc_id = %s
                  AND NOT EXISTS (
                      SELECT 1 FROM public.ner_human_review h
                      WHERE h.doc_id = d.doc_id
                  )
                ORDER BY d.sentence_id
                """,
                (doc_id,),
            ).fetchall()
    return rows


st.title("배정 밖 기사 확인")
st.caption("원본 기사 중 검수 배정표에 기사 ID가 없는 기사를 확인합니다. 목록은 20건씩 조회합니다.")

try:
    presses = load_presses()
    if not presses:
        st.info("원본 기사가 없습니다.")
        st.stop()
    press = st.selectbox("언론사", presses, key="unassigned_press")
    exact_doc_id = st.text_input("기사 ID로 바로 찾기", placeholder="정확한 기사 ID 입력").strip()

    if exact_doc_id:
        with get_postgre_connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                match = cursor.execute(
                    """
                    SELECT d.doc_id FROM public.ner_documents d
                    WHERE d.publisher = %s AND d.doc_id = %s
                      AND NOT EXISTS (
                          SELECT 1 FROM public.ner_human_review h WHERE h.doc_id = d.doc_id
                      )
                    LIMIT 1
                    """,
                    (press, exact_doc_id),
                ).fetchone()
        article_ids = [match["doc_id"]] if match else []
        has_next = False
    else:
        if st.session_state.get("unassigned_page_press") != press:
            st.session_state["unassigned_page_press"] = press
            st.session_state["unassigned_page_starts"] = [""]
        starts = st.session_state["unassigned_page_starts"]
        page_rows, has_next = load_article_page(press, starts[-1])
        article_ids = [row["doc_id"] for row in page_rows]
        st.caption(f"{len(starts)}페이지 · 현재 {len(article_ids)}기사")
        previous, following = st.columns(2)
        if previous.button("이전", disabled=len(starts) == 1):
            starts.pop()
            st.rerun()
        if following.button("다음", disabled=not has_next):
            starts.append(article_ids[-1])
            st.rerun()

    if not article_ids:
        st.info("조건에 맞는 배정 밖 기사가 없습니다.")
        st.stop()
    selected_doc_id = st.selectbox("기사", article_ids)
    sentences = load_article(selected_doc_id)
    if not sentences:
        st.info("이 기사는 현재 배정 대상에 포함되어 있습니다. 목록을 새로고침해 주세요.")
        st.stop()
    st.subheader(sentences[0]["document_title"] or selected_doc_id)
    st.caption(f"{selected_doc_id} · {sentences[0]['date'] or '날짜 없음'} · {sentences[0]['topic'] or '분야 없음'} · {len(sentences)}문장")
    for row in sentences:
        with st.container(border=True):
            st.caption(row["sentence_id"])
            st.write(row["form"])
except Exception as exc:
    st.error(f"배정 밖 기사 조회 실패: {exc}")
