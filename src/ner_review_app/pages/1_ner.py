# -*- coding: utf-8 -*-
import os
import re
import html
import hashlib
import hmac
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
REVIEWER_CREDENTIAL_ENV_PREFIX = "NER_REVIEWER_"
REVIEWER_QUERY_PARAM = "reviewer"
REVIEWER_TOKEN_QUERY_PARAM = "reviewer_token"
BATCH_REVIEW_METHOD = "일괄처리"


def get_reviewer_credentials():
    credentials = {}
    for index in range(1, 5):
        name = os.getenv(f"{REVIEWER_CREDENTIAL_ENV_PREFIX}{index}_NAME")
        password = os.getenv(f"{REVIEWER_CREDENTIAL_ENV_PREFIX}{index}_PASSWORD")
        if name and password:
            credentials[name] = password
    return credentials


def authenticate_reviewer():
    credentials = get_reviewer_credentials()
    authenticated_assignee = st.session_state.get("authenticated_assignee")
    if authenticated_assignee in credentials:
        return authenticated_assignee

    query_assignee = st.query_params.get(REVIEWER_QUERY_PARAM)
    query_token = st.query_params.get(REVIEWER_TOKEN_QUERY_PARAM)
    if query_assignee in credentials and query_token:
        expected_token = hmac.new(
            credentials[query_assignee].encode("utf-8"),
            query_assignee.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if hmac.compare_digest(query_token, expected_token):
            st.session_state.authenticated_assignee = query_assignee
            return query_assignee

    st.info("NER 검수 담당자 인증")
    if not credentials:
        st.error("검수 담당자 계정이 설정되지 않았습니다.")
        st.stop()

    with st.form("reviewer_login"):
        assignee = st.selectbox("담당자", sorted(credentials))
        password = st.text_input("비밀번호", type="password")
        submitted = st.form_submit_button("검수 화면 입장", type="primary")

    if submitted:
        if credentials.get(assignee) == password:
            st.session_state.authenticated_assignee = assignee
            st.query_params[REVIEWER_QUERY_PARAM] = assignee
            st.query_params[REVIEWER_TOKEN_QUERY_PARAM] = hmac.new(
                password.encode("utf-8"),
                assignee.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            st.rerun()
        st.error("담당자 또는 비밀번호가 올바르지 않습니다.")

    st.stop()


def review_widget_key(prefix, sentence_key):
    key = hashlib.md5(repr(sentence_key).encode("utf-8")).hexdigest()
    return f"{prefix}_{key}"


def review_value_key(sentence_key):
    return review_widget_key("modified_value", sentence_key)


def get_modified_form(sentence_key, item):
    return st.session_state.get(
        review_value_key(sentence_key),
        st.session_state.get(
            review_widget_key("modified_form", sentence_key),
            item.get("modified_form") or item.get("original_form") or "",
        ),
    )


def mark_no_issue(status_key, modified_key, original_form):
    st.session_state[status_key] = "완료"
    st.session_state[modified_key] = original_form


def mark_review_complete(status_key):
    st.session_state[status_key] = "완료"


def is_modified_form(current_form, original_form):
    return (current_form or "") != (original_form or "")


def highlighted_tag_spans(form, matches):
    """Return tagged-entity spans which overlap the currently highlighted matches."""
    form = form or ""
    patterns = {
        pattern_part.strip()
        for _, pattern in matches
        if pattern != "패턴 없음"
        for pattern_part in re.split(r",\s*|\r?\n", str(pattern))
        if pattern_part.strip()
    }
    if not patterns:
        return []

    highlighted_spans = []
    for pattern in sorted(patterns, key=len, reverse=True):
        highlighted_spans.extend(
            (match.start(), match.end())
            for match in re.finditer(re.escape(pattern), form)
        )

    tag_pattern = re.compile(r"<([^<>:]+?)\s*:\s*[^<>]+?>")
    return [
        match.span()
        for match in tag_pattern.finditer(form)
        if any(
            tag_start < highlighted_end and highlighted_start < tag_end
            for highlighted_start, highlighted_end in highlighted_spans
            for tag_start, tag_end in [match.span()]
        )
    ]


def convert_batch_form(form, matches=()):
    """Convert only tagged entities included in the highlighted error matches."""
    form = form or ""
    target_spans = set(highlighted_tag_spans(form, matches))
    tag_pattern = re.compile(r"<([^<>:]+?)\s*:\s*[^<>]+?>")

    def replace_tag(match):
        return match.group(1) if match.span() in target_spans else match.group(0)

    return tag_pattern.sub(replace_tag, form)


def apply_batch_processing(sentence_keys, grouped):
    changed_count = 0
    for sentence_key in sentence_keys:
        item = grouped[sentence_key]
        modified_key = review_widget_key("modified_form", sentence_key)
        status_key = review_widget_key("review_status", sentence_key)
        current_form = get_modified_form(sentence_key, item)
        converted_form = convert_batch_form(current_form, item.get("matches", set()))
        if converted_form != current_form:
            st.session_state[review_value_key(sentence_key)] = converted_form
            st.session_state[modified_key] = converted_form
            st.session_state[status_key] = "미완료"
            changed_count += 1

    st.session_state["batch_processing_message"] = (
        f"{changed_count:,}개 문장을 일괄처리했습니다. 내용을 확인한 후 일괄저장을 눌러주세요."
    )


def mark_review_complete_if_modified(
    status_key,
    modified_key,
    original_form,
    item=None,
    assignee=None,
    review_method=None,
):
    value_key = modified_key.replace("modified_form_", "modified_value_", 1)
    current_form = st.session_state.get(modified_key, st.session_state.get(value_key, ""))
    if not is_modified_form(current_form, original_form):
        st.toast("수정된 내용이 없습니다.")
        return
    st.session_state[value_key] = current_form
    st.session_state[status_key] = "완료"
    if item and assignee and review_method != BATCH_REVIEW_METHOD:
        save_review_item(item, assignee, current_form, "완료")
    st.toast("수정완료로 저장되었습니다.")


def mark_no_issue_if_unmodified(
    status_key,
    modified_key,
    original_form,
    item=None,
    assignee=None,
    review_method=None,
):
    value_key = modified_key.replace("modified_form_", "modified_value_", 1)
    current_form = st.session_state.get(modified_key, st.session_state.get(value_key, ""))
    if is_modified_form(current_form, original_form):
        st.toast("수정된 문장이 있습니다. 수정 후 완료를 선택해야합니다.")
        return
    st.session_state[status_key] = "완료"
    st.session_state[modified_key] = original_form
    st.session_state[value_key] = original_form
    if item and assignee and review_method != BATCH_REVIEW_METHOD:
        save_review_item(item, assignee, original_form, "완료")
    st.toast("이상없음으로 저장되었습니다.")


def save_review_page(review_updates, assignee):
    """현재 페이지의 검수 결과를 ner_human_review에 저장한다."""
    query = """
        UPDATE public.ner_human_review
        SET modified_form = %s,
            review_status = %s,
            is_modified = %s,
            updated_at = CASE
                WHEN %s = '완료' THEN COALESCE(updated_at, CURRENT_TIMESTAMP)
                ELSE NULL
            END
        WHERE data_version = %s
          AND press = %s
          AND doc_id = %s
          AND sentence_id = %s
          AND assignee = %s
    """

    with get_postgre_connect() as conn:
        with conn.cursor() as cursor:
            cursor.executemany(query, [(*update, assignee) for update in review_updates])


def save_review_item(item, assignee, modified_form, review_status):
    save_review_page(
        [
            (
                modified_form,
                review_status,
                is_modified_form(modified_form, item.get("original_form")),
                review_status,
                item["data_version"],
                item["press"],
                item["doc_id"],
                item["sentence_id"],
            )
        ],
        assignee,
    )
    fetch_rule_results.clear()


def save_review_draft(item, assignee, review_method=None):
    sentence_key = (item["data_version"], item["doc_id"], item["sentence_id"])
    modified_key = review_widget_key("modified_form", sentence_key)
    status_key = review_widget_key("review_status", sentence_key)
    modified_form = st.session_state.get(modified_key, "")
    # 화면에서 사라진 text_area의 위젯 상태가 정리되어도 유지되도록 별도 상태에 보관한다.
    st.session_state[review_value_key(sentence_key)] = modified_form
    review_status = st.session_state.get(status_key, item.get("review_status") or "미완료")
    if review_method == BATCH_REVIEW_METHOD:
        # 일괄처리 모드는 완료 버튼과 일괄 저장 버튼이 상태 변경을 담당한다.
        return
    if is_modified_form(modified_form, item.get("original_form")):
        review_status = "미완료"
        st.session_state[status_key] = review_status
    save_review_item(item, assignee, modified_form, review_status)

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_press_versions():
    with get_postgre_connect() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT press, data_version
            FROM public.ner_human_review
            WHERE press IS NOT NULL
              AND data_version IS NOT NULL
            ORDER BY press, data_version
            """
        ).fetchall()

    press_versions = {}
    for row in rows:
        data_version = row["data_version"]
        press = row["press"]
        press_versions.setdefault(press, []).append(data_version)
    return press_versions


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_rule_results(
    selected_press,
    data_versions,
    selected_rules,
    limit,
    offset,
    review_method=None,
    assignee=None,
):
    condition = " OR ".join(f'r."{rule}" IS TRUE' for rule in selected_rules)
    review_method_condition = ""
    join_review_method_condition = ""
    query_params = [selected_press, data_versions, assignee]
    if review_method:
        review_method_condition = "AND h.review_method = %s"
        join_review_method_condition = "AND h.review_method = %s"
        query_params.append(review_method)

    rule_match_condition = "" if review_method == "휴먼검수" or not selected_rules else f"""
              AND (
                  NOT EXISTS (
                      SELECT 1
                      FROM public.ner_rule_results_3 AS r_any
                      WHERE r_any.data_version = h.data_version
                        AND regexp_replace(r_any.data_version, '^.*_', '') = h.press
                        AND r_any.doc_id = h.doc_id
                        AND r_any.sentence_id = h.sentence_id
                  )
                  OR EXISTS (
                      SELECT 1
                      FROM public.ner_rule_results_3 AS r
                      WHERE r.data_version = h.data_version
                        AND regexp_replace(r.data_version, '^.*_', '') = h.press
                        AND r.doc_id = h.doc_id
                        AND r.sentence_id = h.sentence_id
                        AND ({condition})
                  )
              )
    """

    select_columns = ",\n            ".join(
        column
        for rule in selected_rules
        for column in (
            [f'r."{rule}"']
            if rule == "EXT_S003"
            else [f'r."{rule}"', f'r."{rule}_PATTERN"']
        )
    )
    if not select_columns:
        select_columns = "NULL AS rule_result_placeholder"

    query = f"""
        WITH filtered_docs AS (
            SELECT DISTINCT h.data_version, h.press, h.doc_id
            FROM public.ner_human_review AS h
            WHERE h.press = %s
              AND h.data_version = ANY(%s)
              AND h.doc_id IS NOT NULL
              AND h.assignee = %s
              {review_method_condition}
              {rule_match_condition}
        ), target_docs AS (
            SELECT
                data_version,
                press,
                doc_id,
                (SELECT COUNT(DISTINCT (press, doc_id)) FROM filtered_docs) AS filtered_article_count
            FROM filtered_docs
            ORDER BY data_version, doc_id
            LIMIT %s OFFSET %s
        )
        SELECT
            h.data_version AS data_version,
            h.press AS press,
            h.doc_id AS doc_id,
            h.sentence_id AS sentence_id,
            h.original_form AS original_form,
            h.modified_form AS modified_form,
            h.review_method AS review_method,
            h.review_status AS review_status,
            h.is_modified AS is_modified,
            t.filtered_article_count AS filtered_article_count,
            r.entity_id,
            r.entity_tagging,
            {select_columns}
        FROM target_docs AS t
        JOIN public.ner_human_review AS h
          ON h.data_version = t.data_version
         AND h.press = t.press
         AND h.assignee = %s
         AND h.doc_id = t.doc_id
         {join_review_method_condition}
        LEFT JOIN public.ner_rule_results_3 AS r
          ON r.data_version = h.data_version
         AND regexp_replace(r.data_version, '^.*_', '') = h.press
         AND r.doc_id = h.doc_id
         AND r.sentence_id = h.sentence_id
         {f'AND ({condition})' if selected_rules else ''}
        ORDER BY h.data_version, h.doc_id, h.sentence_id, r.entity_id
    """

    with get_postgre_connect() as conn:
        rows = conn.execute(
            query,
            (*query_params, limit, offset, assignee, review_method)
            if review_method
            else (*query_params, limit, offset, assignee),
        ).fetchall()
    filtered_article_count = int(rows[0]["filtered_article_count"]) if rows else 0
    return rows, filtered_article_count


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
        press = row["press"]
        sentence_key = (data_version, doc_id, sentence_id)

        item = grouped.setdefault(
            sentence_key,
            {
                "data_version": data_version,
                "press": press,
                "doc_id": doc_id,
                "sentence_id": sentence_id,
                "original_form": row.get("original_form") or "",
                "modified_form": (
                    row.get("modified_form")
                    if row.get("modified_form") is not None
                    else row.get("original_form") or ""
                ),
                "review_method": row.get("review_method"),
                "review_status": row.get("review_status"),
                "is_modified": row.get("is_modified", False),
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
        for pattern_part in re.split(r",\s*|\r?\n", str(pattern))
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
    form = " ".join(item["original_form"].split())
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
authenticated_assignee = authenticate_reviewer()
ner_header_placeholder = st.empty()

try:
    requested_press = st.query_params.get("press")
    requested_review_method = st.query_params.get("review_method")
    if requested_review_method not in {"일괄처리", "LLM검수", "휴먼검수"}:
        requested_review_method = None

    press_versions = fetch_press_versions()

except Exception as exc:
    st.error(f"데이터 조회 실패: {exc}")
    st.stop()

if not press_versions:
    st.info("조회 가능한 데이터가 없습니다.")
    st.stop()
    
# -----------------------------------------------------------------------------
# 다중 선택 드롭다운
# -----------------------------------------------------------------------------
def set_all_checkboxes(options, key_prefix, checked):
    """전체 선택 및 해제"""
    for option in options:
        st.session_state[f"{key_prefix}_{option}"] = checked


def multi_select_filter(label, options, default, format_func, key):
    # 최초 실행 시 기본값 설정
    for option in options:
        widget_key = f"{key}_{option}"
        if widget_key not in st.session_state:
            st.session_state[widget_key] = option in default

    selected = [
        option for option in options
        if st.session_state[f"{key}_{option}"]
    ]

    # 기존 selectbox와 유사한 드롭다운
    with st.sidebar.popover(
        f"{label} ({len(selected)}개 선택)",
        width="stretch",
    ):
        col1, col2 = st.columns(2)

        with col1:
            st.button(
                "전체 선택",
                key=f"{key}_select_all",
                width="stretch",
                on_click=set_all_checkboxes,
                args=(options, key, True),
            )

        with col2:
            st.button(
                "전체 해제",
                key=f"{key}_clear_all",
                width="stretch",
                on_click=set_all_checkboxes,
                args=(options, key, False),
            )

        st.divider()

        for option in options:
            st.checkbox(
                format_func(option),
                key=f"{key}_{option}",
            )

    return tuple(
        option for option in options
        if st.session_state[f"{key}_{option}"]
    )

# -----------------------------------------------------------------------------
# 좌측 사이드바 - 필터
# -----------------------------------------------------------------------------
press_options = sorted(press_versions)
if requested_press in press_options:
    st.session_state.selected_press = requested_press
elif st.session_state.get("selected_press") not in press_options:
    st.session_state.selected_press = press_options[0]

with st.sidebar.popover(f"언론사 ({st.session_state.selected_press})", width="stretch"):
    selected_press = st.radio(
        "언론사 선택",
        press_options,
        key="selected_press",
        label_visibility="collapsed",
    )

selected_press = st.session_state.selected_press

review_method_display_names = {
    "일괄처리": "일괄처리",
    "LLM검수": "휴먼검수",
    "휴먼검수": "계엄기사",
}
review_method_db_by_display = {
    display_name: db_value
    for db_value, display_name in review_method_display_names.items()
}
review_method_options = ["전체", *review_method_display_names.values()]
default_review_method = review_method_display_names.get(requested_review_method, "전체")
if st.session_state.get("selected_review_method_display") not in review_method_options:
    st.session_state.selected_review_method_display = default_review_method

with st.sidebar.popover(
    f"검수 방식 ({st.session_state.selected_review_method_display})",
    width="stretch",
):
    st.radio(
        "검수 방식 선택",
        review_method_options,
        key="selected_review_method_display",
        label_visibility="collapsed",
    )
selected_review_method_display = st.session_state.selected_review_method_display
selected_review_method = (
    None
    if selected_review_method_display == "전체"
    else review_method_db_by_display[selected_review_method_display]
)

selected_types = multi_select_filter(
    "오류유형",
    RULE_TYPES,
    RULE_TYPES,
    lambda value: f"{RULE_TYPE_NAMES.get(value, value)} ({value})",
    "selected_type",
)

available_rules = tuple(
    rule
    for rule_type in selected_types
    for rule in RULES_BY_TYPE[rule_type]
)

# 오류유형 변경 시 세부유형 체크 상태 정리
available_signature = tuple(available_rules)

if st.session_state.get("available_rule_signature") != available_signature:
    for rule in available_rules:
        st.session_state[f"selected_rule_{rule}"] = True

    st.session_state["available_rule_signature"] = available_signature

selected_rules = multi_select_filter(
    "세부유형",
    available_rules,
    available_rules,
    lambda value: f"{RULE_NAMES.get(value, value)} ({value})",
    "selected_rule",
)

with ner_header_placeholder.container(border=False):
    selected_type_names = [
        RULE_TYPE_NAMES.get(value, value)
        for value in selected_types
    ] if selected_review_method_display != "계엄기사" else []
    selected_type_display = (
        "  ".join(
            f'''{html.escape(rule_name)} <span style="
                color:#64748b;
                background-color:#f1f5f9;
                border-radius:4px;
                padding:2px 6px;
                font-size:11px;
                font-weight:400;
            ">{html.escape(rule)}</span>'''
            for rule_name, rule in zip(selected_type_names, selected_types)
        )
        if selected_type_names
        else "없음"
    )

    st.markdown(
        f"""
        <style>
        .ner-info {{
            border: 1px solid #E2E8F0;
            border-radius: 6px;
            padding: 10px 14px;
            margin-bottom: 8px;
            font-size: 14px;
        }}
        .ner-info strong {{
            color: #222222;
            font-weight: 600;
        }}
        .ner-info span {{
            font-weight: 500;
        }}
        </style>

        <div class="ner-info"><strong>언론사</strong> : <span>{selected_press}</span></div>
        <div class="ner-info"><strong>검수방식</strong> : <span>{selected_review_method_display}</span></div>
        <div class="ner-info"><strong>오류유형</strong> : <span>{selected_type_display}</span></div>
        """,
        unsafe_allow_html=True,
    )

filter_key = (selected_press, selected_review_method, selected_types, selected_rules)

if st.session_state.get("rule_filter_key") != filter_key:
    st.session_state["rule_filter_key"] = filter_key
    st.session_state["rule_offset"] = 0

offset = st.session_state.get("rule_offset", 0)
st.sidebar.markdown(
    """
    <style>
    /* 드롭다운 버튼 */
    [data-testid="stSidebar"] [data-testid="stPopover"] > button {
        background-color: white !important;
        border: 1px solid #e0e0e0 !important;
        border-radius: 8px !important;
        min-height: 44px !important;
        padding: 0 12px !important;
        color: #31333f !important;
        font-size: 14px !important;
        font-weight: 400 !important;
    }

    /* 드롭다운 텍스트 좌측 정렬 */
    [data-testid="stSidebar"] [data-testid="stPopover"] > button > div {
        display: flex !important;
        align-items: center !important;
        justify-content: space-between !important;
        width: 100% !important;
    }

    [data-testid="stSidebar"] [data-testid="stPopover"] > button p {
        text-align: left !important;
        width: 100% !important;
        margin: 0 !important;
    }

    /* 팝오버 내부 전체 선택·해제 버튼 */
    [data-testid="stPopoverBody"] [data-testid="stHorizontalBlock"] {
        gap: 6px !important;
    }

    [data-testid="stPopoverBody"] [data-testid="stButton"] {
        margin-bottom: -12px !important;
    }

    [data-testid="stPopoverBody"] [data-testid="stButton"] button {
        min-height: 26px !important;
        height: 26px !important;
        padding: 0 6px !important;
        font-size: 12px !important;
        border-radius: 5px !important;
    }

    /* 전체 선택·해제 버튼 텍스트 좌측 정렬 */
    [data-testid="stPopoverBody"] [data-testid="stButton"] button p {
        text-align: center !important;
        margin: 0 !important;
    }

    /* 체크박스 목록 간격 */
    [data-testid="stPopoverBody"] [data-testid="stCheckbox"] {
        padding: 0 !important;
        margin-top: -4px !important;
        margin-bottom: -4px !important;
    }

    /* 팝오버 내부 구분선 제거 */
    [data-testid="stPopoverBody"] hr {
        display: none !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# 선택 조건에 해당하는 문장 조회
# -----------------------------------------------------------------------------
try:
    rows, filtered_article_count = fetch_rule_results(
        selected_press,
        press_versions[selected_press],
        selected_rules,
        PAGE_SIZE + 1,
        offset,
        selected_review_method,
        authenticated_assignee,
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

# 현재 페이지에 실제 표시되는 문장의 임시 검수 상태와 수정문을 초기화한다.
visible_sentence_keys = [
    sentence_key
    for doc_key in display_doc_keys
    for sentence_key in docs[doc_key]
]
for sentence_key in visible_sentence_keys:
    item = grouped[sentence_key]
    status_key = review_widget_key("review_status", sentence_key)
    modified_key = review_widget_key("modified_form", sentence_key)
    if status_key not in st.session_state:
        st.session_state[status_key] = item.get("review_status") or "미완료"
    value_key = review_value_key(sentence_key)
    if value_key not in st.session_state:
        st.session_state[value_key] = item.get("modified_form") or item.get("original_form") or ""
    # text_area 위젯은 기사 전환 시 제거될 수 있으므로 매 렌더링마다 영속 상태에서 복원한다.
    st.session_state[modified_key] = st.session_state[value_key]

# -----------------------------------------------------------------------------
# 좌측 사이드바 - 검수 기사 목록 및 페이지 이동
# -----------------------------------------------------------------------------
page_sentence_keys = visible_sentence_keys
all_page_completed = bool(page_sentence_keys) and all(
    st.session_state.get(review_widget_key("review_status", sentence_key)) == "완료"
    for sentence_key in page_sentence_keys
)

st.sidebar.markdown(
    f"""<div style="font-size:15px; font-weight:600; margin-bottom:2px;">검수 기사 목록 ({filtered_article_count:,}건)</div>""",
    unsafe_allow_html=True,
)

if display_doc_keys:
    selection_key = "selected_doc_" + hashlib.md5(
        f"{selected_press}|{selected_types}|{selected_rules}|{offset}".encode("utf-8")
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
    st.info("현재 담당자로 배정된 기사가 없습니다.")

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
        margin-bottom: -20px !important;
    }
    """,
    unsafe_allow_html=True,
)

prev_col, page_col, next_col = st.sidebar.columns([0.5, 2, 0.5])

with prev_col:
    st.button(
        "‹",
        disabled=offset == 0,
        width="stretch",
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
        width="stretch",
        help="다음 페이지",
        key="next_doc_page",
        on_click=lambda: st.session_state.update(
            rule_offset=offset + PAGE_SIZE
        ),
    )

# -----------------------------------------------------------------------------
# 본문 - 선택한 기사에 포함된 문장 표시
# -----------------------------------------------------------------------------
def render_sentence_layout(idx, sentence_key, item, sentence_id, matches):
    status_key = review_widget_key("review_status", sentence_key)
    modified_key = review_widget_key("modified_form", sentence_key)
    status = st.session_state.get(status_key, item.get("review_status") or "상태 없음")

    edit_col, rule_col = st.columns([3, 1])
    with edit_col:
        with st.container(border=True, height=410):
            if status == "완료":
                completion_label = (
                    "수정완료"
                    if is_modified_form(
                        get_modified_form(sentence_key, item),
                        item.get("original_form") or "",
                    )
                    else "이상없음"
                )
                st.success(f"문장 {idx:02d}: {sentence_id} · {completion_label}")
            else:
                st.markdown(f"`문장 {idx:02d}: {sentence_id}` `검수 상태: {status}`")
            st.markdown('<div style="margin-bottom:0.35rem; font-weight:600;">원문</div>', unsafe_allow_html=True)
            st.markdown(
                f"""<div style="min-height:100px; padding:0.75rem; border-radius:0.5rem; background-color:rgb(240, 242, 246); white-space:pre-wrap; word-break:break-word;">{highlighted_form(item["original_form"], matches)}</div>""",
                unsafe_allow_html=True,
            )
            st.markdown('<div style="margin-top:0.9rem; margin-bottom:0.35rem; font-weight:600;">수정문</div>', unsafe_allow_html=True)
            st.text_area(
                "수정문 입력",
                key=modified_key,
                height=100,
                label_visibility="collapsed",
                on_change=save_review_draft,
                args=(item, authenticated_assignee, selected_review_method),
            )
            if selected_review_method == BATCH_REVIEW_METHOD:
                action_col, no_issue_col = st.columns(2, gap="small")
            else:
                action_col, no_issue_col = st.columns(2)
            with action_col:
                st.button(
                    "수정완료",
                    key=review_widget_key("complete_modified", sentence_key),
                    width="stretch",
                    on_click=mark_review_complete_if_modified,
                    args=(
                        status_key,
                        modified_key,
                        item["original_form"],
                        item,
                        authenticated_assignee,
                        selected_review_method,
                    ),
                )
            with no_issue_col:
                st.button(
                    "이상없음",
                    key=review_widget_key("complete_no_issue", sentence_key),
                    width="stretch",
                    disabled=is_modified_form(
                        get_modified_form(sentence_key, item),
                        item["original_form"],
                    ),
                    on_click=mark_no_issue_if_unmodified,
                    args=(
                        status_key,
                        modified_key,
                        item["original_form"],
                        item,
                        authenticated_assignee,
                        selected_review_method,
                    ),
                )
    with rule_col:
        with st.container(border=True, height=410):
            st.markdown(
                """
                <div style="font-size:14px; font-weight:600; margin-bottom:4px;">
                    의심 되는 오류 유형
                </div>
                """,
                unsafe_allow_html=True,
            )

            if matches:
                for rule, _ in matches:
                    rule_name = RULE_NAMES.get(rule, rule)

                    st.markdown(
                        f"""
                        <div style="
                            display:flex;
                            align-items:center;
                            gap:7px;
                            padding:5px 0;
                            font-size:13px;
                        ">
                            <span style="color:#64748b;">•</span>
                            <span style="color:#334155; font-weight:600;">
                                {rule_name}
                            </span>
                            <span style="
                                color:#64748b;
                                background-color:#f1f5f9;
                                border-radius:4px;
                                padding:2px 6px;
                                font-size:11px;
                                font-weight:400;
                            ">
                                {rule}
                            </span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("해당 없음")


if selected_doc_key is None:
    st.info("좌측 사이드바에서 기사를 선택하면 검수 대상 문장이 표시됩니다.")

else:
    selected_sentence_keys = docs[selected_doc_key]
    selected_doc_id = selected_doc_key[1]

    if selected_review_method == BATCH_REVIEW_METHOD:
        # 일괄처리 대상은 현재 페이지가 아니라 선택 언론사의 전체 대상 문장이다.
        all_batch_rows, _ = fetch_rule_results(
            selected_press,
            press_versions[selected_press],
            selected_rules,
            max(filtered_article_count, 1),
            0,
            selected_review_method,
            authenticated_assignee,
        )
        batch_grouped = group_sentences(all_batch_rows, selected_rules)
        batch_sentence_keys = list(batch_grouped)

        batch_processing_message = st.session_state.pop("batch_processing_message", None)
        if batch_processing_message:
            st.success(batch_processing_message)
        action_layout_col, _ = st.columns([3, 1])
        with action_layout_col:
            with st.container():
                batch_col, save_col = st.columns(2, gap="small")
                with batch_col:
                    st.button(
                        "일괄처리",
                        key="batch_processing_button",
                        width="stretch",
                        help="선택 언론사의 하이라이트된 <개체명: 태그>만 개체명으로 변환합니다.",
                        on_click=apply_batch_processing,
                        args=(batch_sentence_keys, batch_grouped),
                    )
                with save_col:
                    if st.button(
                        "일괄저장",
                        key="batch_save_review_button",
                        width="stretch",
                        help="선택 언론사의 모든 수정된 일괄처리 문장을 DB에 저장합니다.",
                    ):
                        review_updates = []
                        for sentence_key in batch_sentence_keys:
                            item = batch_grouped[sentence_key]
                            modified_form = get_modified_form(sentence_key, item)
                            review_status = "완료"
                            st.session_state[
                                review_widget_key("review_status", sentence_key)
                            ] = review_status
                            review_updates.append(
                                (
                                    modified_form,
                                    review_status,
                                    is_modified_form(modified_form, item.get("original_form")),
                                    review_status,
                                    item["data_version"],
                                    item["press"],
                                    item["doc_id"],
                                    item["sentence_id"],
                                )
                            )

                        save_review_page(review_updates, authenticated_assignee)
                        fetch_rule_results.clear()
                        st.session_state["batch_processing_message"] = (
                            "일괄처리 결과를 DB에 저장했습니다."
                        )
                        st.rerun()
    # 문장별 검수 영역
    for idx, sentence_key in enumerate(selected_sentence_keys, start=1):
        item = grouped[sentence_key]
        sentence_id = item["sentence_id"]
        matches = sorted(
            item["matches"],
            key=lambda value: (value[0], value[1])
        )

        with st.container():
            render_sentence_layout(idx, sentence_key, item, sentence_id, matches)
            continue
