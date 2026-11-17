# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER 검수 결과 조회 화면
# * 작성일: 2026-11-08
# * 설명: PostgreSQL에 적재된 검수 결과를 확인하는 Streamlit 화면
# ***************************************************
import sys
import streamlit as st
from pathlib import Path
from src.postgresql.query_reviews import fetch_doc_ids, fetch_reviews, fetch_run_folders

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

st.set_page_config(page_title="NER 검수 결과 조회", layout="wide")
st.title("NER 검수 결과 조회")
st.caption("PostgreSQL에 적재된 검수 결과를 간단히 확인합니다.")

try:
    run_rows = fetch_run_folders()
except Exception as exc:
    st.error(f"PostgreSQL에 연결할 수 없습니다: {exc}")
    st.info("POSTGRES_DSN 또는 POSTGRES_HOST/DB/USER/PASSWORD 환경변수를 확인하세요.")
    st.stop()

if not run_rows:
    st.info("PostgreSQL에 적재된 검수 결과가 없습니다.")
    st.stop()

run_folders = [row["run_folder"] for row in run_rows]
selected_run_folder = st.sidebar.selectbox("실행 폴더", run_folders)

doc_rows = fetch_doc_ids(selected_run_folder)
doc_ids = [row["doc_id"] for row in doc_rows]
selected_doc_id = st.sidebar.selectbox("문서 ID", doc_ids)

reviews = fetch_reviews(selected_run_folder, selected_doc_id)
st.write(f"실행 폴더: `{selected_run_folder}`")
st.write(f"문서 ID: `{selected_doc_id}`")
st.metric("검수 결과 건수", len(reviews))

if not reviews:
    st.info("선택한 문서의 검수 결과가 없습니다.")
    st.stop()

st.subheader("문장별 검수 결과")
for sentence_id in sorted({review["sentence_id"] for review in reviews}):
    sentence_reviews = [review for review in reviews if review["sentence_id"] == sentence_id]
    source_sentence = sentence_reviews[0].get("source_sentence") or ""

    with st.expander(f"{sentence_id} · {len(sentence_reviews)}건", expanded=True):
        st.text_area("원문", value=source_sentence, disabled=True, key=f"source_{sentence_id}")
        st.dataframe(
            [
                {
                    "review_id": review["review_id"],
                    "review_status": review["review_status"],
                    "target_span": review["target_span"],
                    "target_type": review["target_type"],
                    "corrected_span": review["corrected_span"],
                    "error_lv1": review["error_lv1"],
                    "error_lv2": review["error_lv2"],
                    "reason": review["reason"],
                    "review_needed": review["review_needed"],
                }
                for review in sentence_reviews
            ],
            use_container_width=True,
            hide_index=True,
        )
