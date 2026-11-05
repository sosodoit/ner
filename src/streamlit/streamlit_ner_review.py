import json
import hashlib
import streamlit as st
from collections import Counter
from pathlib import Path

# ***************************************************
# * function
# ***************************************************
def parse_jsonl(file_bytes: bytes):
    records = []
    text = file_bytes.decode("utf-8-sig")
    for _, line in enumerate(text.splitlines(), start=1):
        record = json.loads(line)
        records.append(record)
    return records

def to_jsonl(records):
    return "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n"

def get_ext_fields(entity):
    fields = sorted(key for key in entity if key.startswith("EXT_"))
    s_fields = [key for key in fields if key.startswith("EXT_S")]
    e_fields = [key for key in fields if key.startswith("EXT_E")]
    return s_fields, e_fields

# ***************************************************
# * 화면
# ***************************************************
st.set_page_config(page_title="구거구거원", page_icon="📝", layout="wide")
st.subheader("개체명 태깅 데이터 휴먼 검수")
st.caption("JSONL 업로드 → 기사 선택 → 문장 수정 및 저장 → 데이터 내보내기")

uploaded_file = st.file_uploader("검수파일(JSONL)", type=["jsonl"])
if uploaded_file is None:
    st.info("검수할 JSONL 파일을 업로드")
    st.stop()

file_bytes = uploaded_file.getvalue()
upload_token = hashlib.sha256(file_bytes).hexdigest()

# ***************************************************
# * session
# ***************************************************
if st.session_state.get("loaded_token") != upload_token:
    st.session_state.records = parse_jsonl(file_bytes)
    st.session_state.loaded_token = upload_token
    st.session_state.source_name = uploaded_file.name

records = st.session_state.records

# ***************************************************
# * 상단
# ***************************************************
article_counts = Counter(record["doc_id"] for record in records)
jsonl_output = to_jsonl(records)
source_stem = Path(st.session_state.source_name).stem

info_col, count_col, export_col = st.columns([3, 1, 1])
with info_col:
    st.write(f"**파일:** {st.session_state.source_name}")
with count_col:
    st.metric("기사", len(article_counts))
with export_col:
    st.download_button(
        label="수정 데이터 내보내기",
        data=jsonl_output,
        file_name=f"{source_stem}_reviewed.jsonl",
        mime="application/x-ndjson",
        use_container_width=True,
    )

st.divider()
left_col, center_col, right_col = st.columns([1.15, 3.7, 2.1], gap="medium")

# ***************************************************
# * 좌측
# ***************************************************
article_ids = list(article_counts.keys())
article_label = {doc_id: f"{doc_id}  ·  {article_counts[doc_id]}문장" for doc_id in article_ids}

with left_col:
    st.subheader("기사 목록")
    selected_doc_id = st.selectbox(
        "검수할 기사 선택",
        options=article_ids,
        format_func=lambda doc_id: article_label[doc_id],
        label_visibility="collapsed",
    )

    selected_count = article_counts[selected_doc_id]
    st.caption(f"선택 기사: {selected_count}개 문장")

selected_records = [
    (index, record)
    for index, record in enumerate(records)
    if record["doc_id"] == selected_doc_id
]

# ***************************************************
# 중앙
# ***************************************************
with center_col:
    st.subheader("문장 편집")
    st.caption(f"기사 ID: {selected_doc_id}")

    for sentence_no, (record_index, record) in enumerate(selected_records, start=1):
        sentence_id = record.get("sentence_id", "문장 ID 없음")
        form_key = f"sentence_form_{upload_token[:12]}_{record_index}"
        text_key = f"sentence_text_{upload_token[:12]}_{record_index}"

        with st.expander(f"문장 {sentence_no}  ·  {sentence_id}", expanded=(sentence_no == 1)):
            with st.form(key=form_key):
                edited_form = st.text_area("기존 문장", value=record.get("form", ""), height=110, key=text_key)
                saved = st.form_submit_button("수정 내용 저장", use_container_width=True)

            if saved:
                st.session_state.records[record_index]["form"] = edited_form
                st.success("수정 내용을 데이터에 반영")

# ***************************************************
# 우측
# ***************************************************
with right_col:
    st.subheader("개체명 검수 항목")
    st.caption("룰 설명 매핑 예정")

    has_any_entity = False
    for sentence_no, (_, record) in enumerate(selected_records, start=1):
        entities = record.get("entities", []) or []
        sentence_id = record.get("sentence_id", "문장 ID 없음")

        with st.expander(f"{sentence_id}  ·  개체명 {len(entities)}개", expanded=(sentence_no == 1)):
            if not entities:
                st.caption("연결된 개체명 없음")
                continue

            for entity_no, entity in enumerate(entities, start=1):
                has_any_entity = True
                entity_name = (entity.get("entity_name") or entity.get("temp_entity_name") or "개체명 없음")
                entity_type = entity.get("entity_type", "태그 없음")
                entity_id = entity.get("entity_id", "개체명 ID 없음")
                s_fields, e_fields = get_ext_fields(entity)

                with st.container(border=True):
                    st.write(f"**{entity_name}**  ·  `{entity_type}`")
                    st.caption(f"{entity_id}")

                    if s_fields:
                        st.caption("문장 검수 항목")
                        st.write("　|　".join(f"{field}: {entity.get(field, '')}" for field in s_fields))

                    if e_fields:
                        st.caption("개체명 검수 항목")
                        st.write("　|　".join(f"{field}: {entity.get(field, '')}" for field in e_fields))

                    if not (s_fields or e_fields):
                        st.caption("검수 항목 없음")

    if not has_any_entity:
        st.caption("선택한 기사에 표시할 개체명 검수 항목이 없음")

# ***************************************************
# 하단
# ***************************************************
st.divider()
st.caption(
    "저장 버튼은 수정한 문장의 form 필드만 현재 입력 데이터에 반영"
    "최종 파일은 상단의 '데이터 내보내기' 버튼으로 다운로드"
)
