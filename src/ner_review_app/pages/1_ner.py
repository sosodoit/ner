# -*- coding: utf-8 -*-
import re
import html
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
PAGE_SIZE = 100

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_press_versions():
    with get_postgre_connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT data_version FROM public.ner_rule_results_3 WHERE data_version IS NOT NULL ORDER BY data_version"
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
        WITH target_sentences AS (
            SELECT DISTINCT sentence_id
            FROM public.ner_rule_results_3
            WHERE data_version = ANY(%s)
              AND ({condition})
            ORDER BY sentence_id
            LIMIT %s OFFSET %s
        )
        SELECT r.sentence_id, r.entity_id, r.form, r.entity_tagging,
               {select_columns}
        FROM public.ner_rule_results_3 AS r
        JOIN target_sentences AS t ON t.sentence_id = r.sentence_id
        WHERE r.data_version = ANY(%s)
        ORDER BY r.sentence_id, r.entity_id
    """
    with get_postgre_connect() as conn:
        return conn.execute(query, (data_versions, limit, offset, data_versions)).fetchall()


def group_sentences(rows, selected_rules):
    grouped = {}
    for row in rows:
        sentence_id = row["sentence_id"]
        item = grouped.setdefault(sentence_id, {"form": row.get("form") or "", "tags": set(), "matches": set()})
        if row.get("entity_tagging"):
            item["tags"].add(row["entity_tagging"])
        for rule in selected_rules:
            if row.get(rule):
                pattern = row.get(f"{rule}_PATTERN")
                item["matches"].add((rule, pattern or "패턴 없음"))
    return grouped


# def highlighted_form(form, matches):
#     result = html.escape(form)
#     patterns = {pattern for _, pattern in matches if pattern != "패턴 없음"}
#     for pattern in sorted(patterns, key=len, reverse=True):
#         escaped_pattern = html.escape(pattern)
#         result = result.replace(
#             escaped_pattern,
#             f'<mark style="background:#ffe08a; padding:1px 2px; border-radius:3px">{escaped_pattern}</mark>',
#         )
#     return f'<div style="white-space:pre-wrap; line-height:1.8">{result}</div>'


def highlighted_form(form, matches):
    patterns = {
        p.strip()
        for _, pattern in matches
        if pattern != "패턴 없음"
        for p in str(pattern).split(", ")
        if p.strip()
    }

    if not patterns:
        return f'<div style="white-space:pre-wrap; line-height:1.8">{html.escape(form)}</div>'

    regex = re.compile("|".join(re.escape(p) for p in sorted(patterns, key=len, reverse=True)))

    highlighted = []
    last_end = 0
    for match in regex.finditer(form):
        highlighted.append(html.escape(form[last_end:match.start()]))
        highlighted.append(
            f'<mark style="background:#ffe08a; padding:1px 2px; border-radius:3px">'
            f'{html.escape(match.group())}</mark>'
        )
        last_end = match.end()
    highlighted.append(html.escape(form[last_end:]))

    return f'<div style="white-space:pre-wrap; line-height:1.8">{"".join(highlighted)}</div>'

st.text("Rule 검출 결과 조회")
st.caption("언론사와 룰을 선택하면 문장 단위로 검출 결과를 표시합니다.")

try:
    press_versions = fetch_press_versions()
except Exception as exc:
    st.error(f"데이터 조회 실패: {exc}")
    st.stop()

if not press_versions:
    st.info("데이터가 없습니다.")
    st.stop()


col1, col2, col3 = st.columns(3)

with col1:
    selected_press = st.selectbox("언론사", sorted(press_versions))

with col2:
    selected_type = st.selectbox(
        "오류유형",
        RULE_TYPES,
        format_func=lambda x: f"{RULE_TYPE_NAMES.get(x, x)} ({x})",
    )
    selected_rules = tuple(RULES_BY_TYPE[selected_type])

with col3:
    selected_rule = st.selectbox(
        "세부유형",
        ["전체 룰", *selected_rules],
        format_func=lambda x: (
            "전체 룰" if x == "전체 룰"
            else f"{RULE_NAMES.get(x, x)} ({x})"
        ),
    )

filter_key = (selected_press, selected_rule)
if st.session_state.get("rule_filter_key") != filter_key:
    st.session_state["rule_filter_key"] = filter_key
    st.session_state["rule_offset"] = 0

offset = st.session_state.get("rule_offset", 0)

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
sentence_ids = list(grouped)
has_next = len(sentence_ids) > PAGE_SIZE
display_ids = sentence_ids[:PAGE_SIZE]

st.write(
    f"**{selected_press}** · "
    f"**{RULE_TYPE_NAMES.get(selected_type, selected_type)}** · "
    f"**{RULE_NAMES.get(selected_rule, selected_rule) if selected_rule != '전체 룰' else '전체 룰'}** · "
    f"조회 문장 {len(display_ids):,}건"
)

if not display_ids:
    st.info("조건에 해당하는 룰 검출 결과가 없습니다.")
else:
    for sentence_id in display_ids:
        item = grouped[sentence_id]
        matches = sorted(item["matches"], key=lambda x: (x[0], x[1]))
        with st.container(border=True):
            st.markdown(f"**{sentence_id}**")
            st.markdown(highlighted_form(item["form"], matches), unsafe_allow_html=True)
            if item["tags"]:
                st.caption("entity_tagging: " + " · ".join(sorted(item["tags"])))
            st.markdown("**검출 룰 및 패턴**")
            for rule, pattern in matches:
                rule_name = RULE_NAMES.get(rule, rule)
                st.text(f"{rule_name} ({rule}) · {pattern}")

prev_col, next_col = st.columns(2)
with prev_col:
    if st.button("이전 100건", disabled=offset == 0, use_container_width=True):
        st.session_state["rule_offset"] = max(0, offset - PAGE_SIZE)
        st.rerun()
with next_col:
    if st.button("다음 100건", disabled=not has_next, use_container_width=True):
        st.session_state["rule_offset"] = offset + PAGE_SIZE
        st.rerun()
