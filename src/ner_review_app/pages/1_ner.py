# -*- coding: utf-8 -*-
import re
import html
import hashlib
import streamlit as st
from src.ner_review_app.modules.postgredb import get_postgre_connect

RULES_BY_TYPE = {
    "EXT_S003": ["EXT_S003"],
    "EXT_E003": [
        "EXT_E003_AF_001",
        "EXT_E003_AF_002",
        "EXT_E003_AF_003",
        "EXT_E003_AF_004",
        "EXT_E003_AF_005",
        "EXT_E003_AF_007",
        "EXT_E003_AF_008",
        "EXT_E003_AF_009",
        "EXT_E003_AF_010",
        "EXT_E003_DT_001",
        "EXT_E003_DT_002",
        "EXT_E003_DT_003",
        "EXT_E003_EV_001",
        "EXT_E003_EV_002",
        "EXT_E003_LC_001",
        "EXT_E003_LC_002",
        "EXT_E003_LC_003",
        "EXT_E003_LC_004",
        "EXT_E003_LC_005",
        "EXT_E003_LC_007",
        "EXT_E003_OG_001",
        "EXT_E003_OG_002",
        "EXT_E003_OG_003",
        "EXT_E003_OG_004",
        "EXT_E003_PS_001",
        "EXT_E003_PS_002",
        "EXT_E003_PS_003",
        "EXT_E003_PS_004",
    ],
    "EXT_E004": [
        "EXT_E004_DT_001",
        "EXT_E004_DT_002",
        "EXT_E004_DT_003",
        "EXT_E004_DT_004",
        "EXT_E004_DT_005",
        "EXT_E004_DT_006",
        "EXT_E004_DT_007",
    ],
    "EXT_E005": [
        "EXT_E005_EV_001",
        "EXT_E005_EV_002",
        "EXT_E005_EV_003",
        "EXT_E005_EV_004",
        "EXT_E005_EV_005",
    ],
    "EXT_E006": [
        "EXT_E006_EV_001",
        "EXT_E006_EV_002",
    ],
}
# 오류유형 화면 표시 명칭
RULE_TYPE_NAMES = {
    "EXT_S003": "DT 개체명 연속 출현",
    "EXT_E003": "태그별 오태깅 의심 개체명",
    "EXT_E004": "DT 개체명의 범위 표현 오류",
    "EXT_E005": "EV 개체명의 숫자 표현 오류",
    "EXT_E006": "EV 개체명의 범위 표현 오류",
}

# 세부유형 화면 표시 명칭
RULE_NAMES = {
    # EXT_E003
    "EXT_E003_AF_001": "법률명",
    "EXT_E003_AF_002": "AI 모델명",
    "EXT_E003_AF_003": "SNS·커뮤니티 앱명",
    "EXT_E003_AF_004": "소프트웨어명",
    "EXT_E003_AF_005": "상품권·플랫폼명",
    "EXT_E003_AF_007": "단독 태깅",
    "EXT_E003_AF_008": "금융 상품",
    "EXT_E003_AF_009": "의류",
    "EXT_E003_AF_010": "전자기기",
    "EXT_E003_DT_001": "수량·횟수 표현",
    "EXT_E003_DT_002": "시간·수량 표현",
    "EXT_E003_DT_003": "반복 기간",
    "EXT_E003_EV_001": "사업·과정명",
    "EXT_E003_EV_002": "칙령·혁명",
    "EXT_E003_LC_001": "국적 표현 (접미형)",
    "EXT_E003_LC_002": "국적 표현 (내부 결합형)",
    "EXT_E003_LC_003": "단독 태깅",
    "EXT_E003_LC_004": "꽃밭 포함",
    "EXT_E003_LC_005": "고개·바위",
    "EXT_E003_LC_007": "지역명",
    "EXT_E003_OG_001": "직책 표현",
    "EXT_E003_OG_002": "단독 태깅",
    "EXT_E003_OG_003": "진료과명",
    "EXT_E003_OG_004": "종교명",
    "EXT_E003_PS_001": "직책형 인물 표현",
    "EXT_E003_PS_002": "익명 인물 표현",
    "EXT_E003_PS_003": "영어 이름 앞 호칭",
    "EXT_E003_PS_004": "유아어",

    # EXT_E004
    "EXT_E004_DT_001": "선행 범위 표현",
    "EXT_E004_DT_002": "후행 근사 표현",
    "EXT_E004_DT_003": "후행 시점 표현",
    "EXT_E004_DT_004": "기간 범위 표현",
    "EXT_E004_DT_005": "후행 내부 범위 표현",
    "EXT_E004_DT_006": "시대·시기 결합 표현",
    "EXT_E004_DT_007": "일수·월수 단위 결합 표현",

    # EXT_E005
    "EXT_E005_EV_001": "연도 포함",
    "EXT_E005_EV_002": "연도·시즌·월 접미 표현",
    "EXT_E005_EV_003": "연도 범위",
    "EXT_E005_EV_004": "기수 표현",
    "EXT_E005_EV_005": "날짜형 숫자 표현",

    # EXT_E006
    "EXT_E006_EV_001": "이벤트 이후 시점 표현",
    "EXT_E006_EV_002": "라운드·회차·경기 표현",
}

RULE_TYPES = list(RULES_BY_TYPE)
PAGE_SIZE = 10

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_press_versions():
    with get_postgre_connect() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT data_version
            FROM public.ner_rule_results_3
            WHERE data_version IS NOT NULL
            ORDER BY data_version
            """
        ).fetchall()

    press_versions = {}
    for row in rows:
        data_version = row["data_version"]
        press = data_version.rsplit("_", 1)[-1]
        press_versions.setdefault(press, []).append(data_version)
    return press_versions

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_rule_results(data_versions, selected_rule, selected_rules, limit, offset):
    target_rules = selected_rules if selected_rule == "전체 룰" else (selected_rule,)
    condition = " OR ".join(f'"{rule}" IS TRUE' for rule in target_rules)

    select_columns = ",\n            ".join(
        column
        for rule in selected_rules
        for column in (
            [f'r."{rule}"']
            if rule == "EXT_S003"
            else [f'r."{rule}"', f'r."{rule}_PATTERN"']
        )
    )

    query = f"""
        WITH target_docs AS (
            SELECT DISTINCT data_version, doc_id
            FROM public.ner_rule_results_3
            WHERE data_version = ANY(%s)
              AND ({condition})
              AND doc_id IS NOT NULL
            ORDER BY data_version, doc_id
            LIMIT %s OFFSET %s
        )
        SELECT
            r.data_version AS data_version,
            r.doc_id AS doc_id,
            r.sentence_id AS sentence_id,
            r.entity_id,
            r.form,
            r.entity_tagging,
            {select_columns}
        FROM public.ner_rule_results_3 AS r
        JOIN target_docs AS t
          ON r.data_version = t.data_version
         AND r.doc_id = t.doc_id
        ORDER BY r.data_version, r.doc_id, r.sentence_id, r.entity_id
    """

    with get_postgre_connect() as conn:
        return conn.execute(
            query,
            (data_versions, limit, offset),
        ).fetchall()


def group_sentences(rows, selected_rules):
    grouped = {}

    for row in rows:
        # SQL SELECT에서 명시적으로 반환한 컬럼만 사용
        doc_id = row.get("doc_id")
        if doc_id is None:
            raise ValueError(
                "조회 결과에 doc_id가 없습니다. fetch_rule_results()의 SELECT에 "
                "r.doc_id AS doc_id가 포함되어 있는지 확인하세요."
            )

        sentence_id = row["sentence_id"]
        data_version = row["data_version"]
        sentence_key = (data_version, doc_id, sentence_id)

        item = grouped.setdefault(
            sentence_key,
            {
                "data_version": data_version,
                "doc_id": doc_id,
                "sentence_id": sentence_id,
                "form": row.get("form") or "",
                "tags": set(),
                "matches": set(),
            },
        )

        if row.get("entity_tagging"):
            item["tags"].add(row["entity_tagging"])

        for rule in selected_rules:
            if row.get(rule):
                pattern = row.get(f"{rule}_PATTERN")
                item["matches"].add((rule, pattern or "패턴 없음"))

    return grouped


def highlighted_form(form, matches):
    patterns = {
        pattern_part.strip()
        for _, pattern in matches
        if pattern != "패턴 없음"
        for pattern_part in str(pattern).split(", ")
        if pattern_part.strip()
    }

    if not patterns:
        return (
            '<div style="white-space:pre-wrap; line-height:1.9; '
            f'font-size:16px">{html.escape(form)}</div>'
        )

    regex = re.compile("|".join(re.escape(p) for p in sorted(patterns, key=len, reverse=True)))
    highlighted = []
    last_end = 0

    for match in regex.finditer(form):
        highlighted.append(html.escape(form[last_end:match.start()]))
        highlighted.append(
            '<mark style="background:#ffe08a; padding:2px 3px; border-radius:4px">'
            f"{html.escape(match.group())}</mark>"
        )
        last_end = match.end()

    highlighted.append(html.escape(form[last_end:]))
    return (
        '<div style="white-space:pre-wrap; line-height:1.9; '
        f'font-size:16px">{"".join(highlighted)}</div>'
    )

def sentence_label(sentence_key, grouped):
    item = grouped[sentence_key]
    sentence_id = item["sentence_id"]
    form = " ".join(item["form"].split())
    preview = form[:34] + ("…" if len(form) > 34 else "")
    return f"{sentence_id}  ·  {preview}" if preview else sentence_id


def document_sort_key(document_key):
    """문서 ID가 숫자 접미사를 갖지 않아도 정렬 가능하도록 한다."""
    data_version, doc_id = document_key
    doc_id = str(doc_id)
    suffix = doc_id.rsplit(".", 1)[-1]
    if suffix.isdigit():
        return data_version, 0, int(suffix), doc_id
    return data_version, 1, suffix, doc_id

# -----------------------------------------------------------------------------
# 데이터 조회
# -----------------------------------------------------------------------------
with st.container(border=True):
    st.markdown("**NER 검수**")
    st.caption("※ 기준테이블: `ner_human_review` `ner_rule_results_3`")

try:
    press_versions = fetch_press_versions()

except Exception as exc:
    st.error(f"데이터 조회 실패: {exc}")
    st.stop()

if not press_versions:
    st.info("조회 가능한 데이터가 없습니다.")
    st.stop()

# -----------------------------------------------------------------------------
# 좌측 사이드바 - 필터
# -----------------------------------------------------------------------------
st.sidebar.markdown("""<div style="font-size:15px; font-weight:600; margin-bottom:2px;">언론사</div>""", unsafe_allow_html=True)
selected_press = st.sidebar.selectbox(
    "언론사 선택",
    sorted(press_versions),
    label_visibility="collapsed",
)

st.sidebar.markdown("""<div style="font-size:15px; font-weight:600; margin-bottom:2px;">오류유형</div>""", unsafe_allow_html=True)
selected_type = st.sidebar.selectbox(
    "오류유형 선택",
    RULE_TYPES,
    format_func=lambda value: f"{RULE_TYPE_NAMES.get(value, value)} ({value})",
    label_visibility="collapsed",
)
selected_rules = tuple(RULES_BY_TYPE[selected_type])

st.sidebar.markdown("""<div style="font-size:15px; font-weight:600; margin-bottom:2px;">세부유형</div>""", unsafe_allow_html=True)
selected_rule = st.sidebar.selectbox(
    "세부유형 선택",
    ["전체 룰", *selected_rules],
    format_func=lambda value: (
        "전체 룰"
        if value == "전체 룰"
        else f"{RULE_NAMES.get(value, value)} ({value})"
    ),
    label_visibility="collapsed",
)

filter_key = (selected_press, selected_type, selected_rule)
if st.session_state.get("rule_filter_key") != filter_key:
    st.session_state["rule_filter_key"] = filter_key
    st.session_state["rule_offset"] = 0

offset = st.session_state.get("rule_offset", 0)

# -----------------------------------------------------------------------------
# 선택 조건에 해당하는 문장 조회
# -----------------------------------------------------------------------------
try:
    rows = fetch_rule_results(
        press_versions[selected_press],
        selected_rule,
        selected_rules,
        PAGE_SIZE + 1,
        offset,
    )
except Exception as exc:
    st.error(f"룰 검출 결과 조회 실패: {exc}")
    st.stop()

grouped = group_sentences(rows, selected_rules)

# 조회 결과를 기사별로 묶기
docs = {}
for sentence_key, item in grouped.items():
    doc_key = (item["data_version"], item["doc_id"])
    docs.setdefault(doc_key, []).append(sentence_key)

doc_keys = sorted(
    docs,
    key=document_sort_key,
)
has_next = len(doc_keys) > PAGE_SIZE
display_doc_keys = doc_keys[:PAGE_SIZE]

st.write(
    f"**{selected_press}** · "
    f"**{RULE_TYPE_NAMES.get(selected_type, selected_type)}** · "
    f"**{RULE_NAMES.get(selected_rule, selected_rule) if selected_rule != '전체 룰' else '전체 룰'}** · "
    f"조회 기사 {len(display_doc_keys):,}건"
)

# -----------------------------------------------------------------------------
# 좌측 사이드바 - 검수 기사 목록 및 페이지 이동
# -----------------------------------------------------------------------------
st.sidebar.markdown("""<div style="font-size:15px; font-weight:600; margin-bottom:2px;">검수 기사 목록</div>""", unsafe_allow_html=True)

if display_doc_keys:
    selection_key = "selected_doc_" + hashlib.md5(
        f"{selected_press}|{selected_type}|{selected_rule}|{offset}".encode("utf-8")
    ).hexdigest()

    selected_doc_key = st.sidebar.radio(
        "기사 선택",
        display_doc_keys,
        format_func=lambda key: key[1],
        key=selection_key,
        label_visibility="collapsed",
        captions=None,
    )
else:
    selected_doc_key = None
    st.sidebar.info("조건에 해당하는 기사가 없습니다.")

# 페이지 이동 영역
st.sidebar.markdown(
    """
    <style>
    /* 기사 목록 간격 */
    [data-testid="stSidebar"] div[role="radiogroup"] {
        gap: 1px;
    }

    [data-testid="stSidebar"] div[role="radiogroup"] label {
        padding-top: 2px;
        padding-bottom: 2px;
        min-height: 26px;
    }

    /* 페이지 이동 버튼 */
    [data-testid="stSidebar"] div[data-testid="stButton"] button {
        min-height: 30px;
        padding: 0 4px;
        border-radius: 6px;
        color: #334155;
    }

    [data-testid="stSidebar"] div[data-testid="stButton"] button:hover {
        background-color: #e8edf5;
        color: #1d4ed8;
    }

    [data-testid="stSidebar"] div[data-testid="stButton"] button:disabled {
        color: #c4cbd5;
    }

    /* 기사 목록 하단 여백 축소 */
    [data-testid="stSidebar"] div[role="radiogroup"] {
        padding-bottom: 0 !important;
        margin-bottom: -40px !important;
    }
    """,
    unsafe_allow_html=True,
)

st.sidebar.divider()

prev_col, page_col, next_col = st.sidebar.columns([0.5, 2, 0.5])

with prev_col:
    st.button(
        "‹",
        disabled=offset == 0,
        use_container_width=True,
        help="이전 페이지",
        key="previous_doc_page",
        on_click=lambda: st.session_state.update(
            rule_offset=max(0, offset - PAGE_SIZE)
        ),
    )

with page_col:
    st.markdown(
        f"""
        <div style="
            text-align:center;
            font-size:12px;
            color:#64748b;
            padding-top:7px;
            white-space:nowrap;
        ">
            {offset // PAGE_SIZE + 1} 페이지
            <span style="color:#94a3b8;">({offset + 1:,}–{offset + len(display_doc_keys):,}건)</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

with next_col:
    st.button(
        "›",
        disabled=not has_next,
        use_container_width=True,
        help="다음 페이지",
        key="next_doc_page",
        on_click=lambda: st.session_state.update(
            rule_offset=offset + PAGE_SIZE
        ),
    )


# -----------------------------------------------------------------------------
# 본문 - 선택한 기사에 포함된 문장 표시
# -----------------------------------------------------------------------------
if selected_doc_key is None:
    st.info("좌측 사이드바에서 기사를 선택하면 검수 대상 문장이 표시됩니다.")

else:
    selected_sentence_keys = docs[selected_doc_key]
    selected_doc_id = selected_doc_key[1]

    st.markdown(
        f"**{selected_press}**  ·  "
        f"**{RULE_TYPE_NAMES.get(selected_type, selected_type)}**  ·  "
        f"**{RULE_NAMES.get(selected_rule, selected_rule) if selected_rule != '전체 룰' else '전체 룰'}**"
    )

    st.markdown(f"### 기사 ID: {selected_doc_id}")
    st.caption(f"조회 문장 {len(selected_sentence_keys):,}건")

    for sentence_key in selected_sentence_keys:
        item = grouped[sentence_key]
        sentence_id = item["sentence_id"]
        matches = sorted(item["matches"], key=lambda value: (value[0], value[1]))

        with st.container(border=True):
            st.markdown(f"**문장 ID: {sentence_id}**")

            st.markdown(
                highlighted_form(item["form"], matches),
                unsafe_allow_html=True,
            )

            if item["tags"]:
                st.caption("개체 태그: " + " · ".join(sorted(item["tags"])))

            if matches:
                st.divider()
                st.caption("룰 검출 결과")

                for rule, pattern in matches:
                    rule_name = RULE_NAMES.get(rule, rule)
                    st.markdown(f"**{rule_name}**  `({rule})`")
                    st.caption(f"탐지 패턴: {pattern}")

            st.divider()
            st.caption("LLM 검수 결과 데이터 연결 예정")
