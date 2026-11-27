# -*- coding: utf-8 -*-
"""휴먼 검수 화면"""
#---------------------------------------------------------------------------------------------------------
# 기본 설정 - 라이브러리 불러오기
#---------------------------------------------------------------------------------------------------------
import os
import re
import html
import hmac
import hashlib
import streamlit as st

#---------------------------------------------------------------------------------------------------------
# 기본 설정 - 검수 공통 모듈 불러오기
#---------------------------------------------------------------------------------------------------------
from src.ner_review.response_input import ENTITY_PATTERN
from src.ner_review_app.modules.postgredb import get_postgre_connect
from src.ner_review_app.modules.review_rows import load_review_rows
from src.ner_review_app.modules.entity_filter import ENTITY_PAGE_SIZE, render_entity_filter
from src.ner_review_app.modules.entity_catalog import entity_search_pattern
from src.ner_review_app.modules.review_targets import HUMAN_REVIEW_METHOD, METHOD_DISPLAY_NAMES, REVIEW_SCOPE_CTES
from src.ner_review_app.modules.review_statistics import load_review_data
from src.ner_review_app.modules._article_list_state import get_article_list_state, remember_article_filters, render_article_selector


#---------------------------------------------------------------------------------------------------------
# 기본 설정 - 오류 유형별 검출 룰
#---------------------------------------------------------------------------------------------------------
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

#---------------------------------------------------------------------------------------------------------
# 기본 설정 - 오류 유형 명칭 및 룰 매핑
#---------------------------------------------------------------------------------------------------------
# 검수결과의 lv1을 공통 오류유형으로 사용한다.
ERROR_TYPE_NAMES = {
    "tagging_error": "태그 오류",
    "tagging_wrong": "오태깅",
    "tagging_miss": "태깅 누락",
    "span_error": "범위 오류",
    "etc": "기타",
}
RULE_GROUP_ERROR_TYPES = {
    "EXT_S003": "span_error",
    "EXT_E003": "tagging_wrong",
    "EXT_E004": "span_error",
    "EXT_E005": "span_error",
    "EXT_E006": "span_error",
}
RULE_ERROR_TYPES = {
    rule: RULE_GROUP_ERROR_TYPES[group]
    for group, rules in RULES_BY_TYPE.items()
    for rule in rules
}

#---------------------------------------------------------------------------------------------------------
# 기본 설정 - 세부 검출 룰 표시 명칭
#---------------------------------------------------------------------------------------------------------
# 세부유형 화면 표시 명칭
# 추후 하위 태그 내용 합쳐서 상위 태그 내용으로만 보이도록
RULE_NAMES = {
    "EXT_S003": "[DT] 태깅병합",

    # EXT_E003
    "EXT_E003_AF_001": "[AF] 법률명",
    "EXT_E003_AF_002": "[AF] 모델명",
    "EXT_E003_AF_003": "[AF] 앱명",
    "EXT_E003_AF_004": "[AF] 소프트웨어명",
    "EXT_E003_AF_005": "[AF] 상품권·플랫폼명",
    "EXT_E003_AF_007": "[AF] 단독태깅제외명사",
    "EXT_E003_AF_008": "[AF] 금융상품",
    "EXT_E003_AF_009": "[AF] 의류보통명사",
    "EXT_E003_AF_010": "[AF] 전자기기",
    "EXT_E003_DT_001": "[DT] 수량·횟수표현",
    "EXT_E003_DT_002": "[DT] 시간·수량표현",
    "EXT_E003_DT_003": "[DT] 반복기간",
    "EXT_E003_EV_001": "[EV] 사업·과정명",
    "EXT_E003_EV_002": "[EV] 칙령",
    "EXT_E003_LC_001": "[LC] 국적표현(접미형)",
    "EXT_E003_LC_002": "[LC] 국적표현(내부결합형)",
    "EXT_E003_LC_003": "[LC] 단독태깅제외명사",
    "EXT_E003_LC_004": "[LC] 꽃밭",
    "EXT_E003_LC_005": "[LC] 고개·바위",
    "EXT_E003_LC_007": "[LC] 지역명",
    "EXT_E003_OG_001": "[OG] 직책표현",
    "EXT_E003_OG_002": "[OG] 기타명사",
    "EXT_E003_OG_003": "[OG] 진료과명",
    "EXT_E003_OG_004": "[OG] 종교명",
    "EXT_E003_PS_001": "[PS] 직책형인물표현",
    "EXT_E003_PS_002": "[PS] 익명표현",
    "EXT_E003_PS_003": "[PS] 영어호칭",
    "EXT_E003_PS_004": "[PS] 유아어",

    # EXT_E004
    "EXT_E004_DT_001": "[DT] 선행표현",
    "EXT_E004_DT_002": "[DT] 후행표현(근사)",
    "EXT_E004_DT_003": "[DT] 후행표현(시점)",
    "EXT_E004_DT_004": "[DT] 기간범위",
    "EXT_E004_DT_005": "[DT] 후행표현(이내)",
    "EXT_E004_DT_006": "[DT] 시대·시기표현",
    "EXT_E004_DT_007": "[DT] 기타표현",

    # EXT_E005
    "EXT_E005_EV_001": "[EV] 연도포함",
    "EXT_E005_EV_002": "[EV] 연도포함(접미)",
    "EXT_E005_EV_003": "[EV] 연도포함(범위)",
    "EXT_E005_EV_004": "[EV] 횟수포함",
    "EXT_E005_EV_005": "[EV] 날짜포함",

    # EXT_E006
    "EXT_E006_EV_001": "[EV] 시점포함",
    "EXT_E006_EV_002": "[EV] 라운드·회차·경기",
}

#---------------------------------------------------------------------------------------------------------
# 기본 설정 - 페이지 크기 및 담당자 인증 설정
#---------------------------------------------------------------------------------------------------------
ERROR_TYPES = tuple(ERROR_TYPE_NAMES)
PAGE_SIZE = 10
TAGGED_ENTITY_PATTERN = re.compile(r"<\s*([^<>:]+?)\s*:\s*([^<>]+?)\s*>")
REVIEWER_CREDENTIAL_ENV_PREFIX = "NER_REVIEWER_"
REVIEWER_QUERY_PARAM = "reviewer"
REVIEWER_TOKEN_QUERY_PARAM = "reviewer_token"
BATCH_REVIEW_METHOD = "일괄처리"
#---------------------------------------------------------------------------------------------------------
# 기본 설정 - 검수 판정 및 오류 안내 문구
#---------------------------------------------------------------------------------------------------------
RESPONSE_STATUS_NAMES = {
    "error": "오류",
    "normal": "정상",
    "unreviewed": "미검수",
    "failed": "검수 실패",
    "pending": "검수 대기",
    None: "미지정",
}
RESPONSE_ERROR_MESSAGES = {
    "tagging_error": "태그 오류가 의심됩니다.",
    "tagging_wrong": "불필요한 태깅이 의심됩니다.",
    "tagging_miss": "태깅 누락이 의심됩니다.",
    "span_error": "태그 범위 오류가 의심됩니다.",
    "etc": "기타 오류가 의심됩니다. 태깅 내용을 확인해 주세요.",
    "span_expansion": "태그 범위를 넓혀야 하는지 확인해 주세요.",
    "span_reduction": "태그 범위를 줄여야 하는지 확인해 주세요.",
    "span_tagging_split": "하나의 태그를 나누어야 하는지 확인해 주세요.",
    "span_tagging_merge": "나뉜 태그를 합쳐야 하는지 확인해 주세요.",
}


#---------------------------------------------------------------------------------------------------------
# 기능 - 담당자 계정 조회 및 로그인 인증
#---------------------------------------------------------------------------------------------------------
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


#---------------------------------------------------------------------------------------------------------
# 기능 - 문장별 위젯 키 및 수정 상태 관리
#---------------------------------------------------------------------------------------------------------
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


#---------------------------------------------------------------------------------------------------------
# 기능 - 강조 대상 추출 및 태그 일괄처리
#---------------------------------------------------------------------------------------------------------
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


def convert_batch_form(form, matches=(), selected_entity=None):
    """Convert only tagged entities included in the highlighted error matches."""
    form = form or ""
    target_spans = set(highlighted_tag_spans(form, matches))

    def replace_tag(match):
        entity = (match[1].strip(), match[2].strip())
        if match.span() in target_spans and (selected_entity is None or entity == selected_entity):
            return match[1]
        return match[0]

    return TAGGED_ENTITY_PATTERN.sub(replace_tag, form)


def apply_batch_processing(sentence_keys, grouped, selected_entity=None):
    changed_count = 0
    for sentence_key in sentence_keys:
        item = grouped[sentence_key]
        modified_key = review_widget_key("modified_form", sentence_key)
        status_key = review_widget_key("review_status", sentence_key)
        current_form = get_modified_form(sentence_key, item)
        converted_form = convert_batch_form(current_form, item.get("matches", set()), selected_entity)
        if converted_form != current_form:
            st.session_state[review_value_key(sentence_key)] = converted_form
            st.session_state[modified_key] = converted_form
            st.session_state[status_key] = "미완료"
            st.session_state[review_widget_key("batch_pending", sentence_key)] = st.session_state.get("rule_filter_key")
            changed_count += 1

    st.session_state["batch_processing_message"] = (
        f"{changed_count:,}개 문장을 일괄처리했습니다. 내용을 확인한 후 일괄저장을 눌러주세요."
    )


#---------------------------------------------------------------------------------------------------------
# 기능 - 수정완료 및 이상없음 처리
#---------------------------------------------------------------------------------------------------------
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
    was_completed = st.session_state.get(status_key) == "완료"
    if not is_modified_form(current_form, original_form):
        st.toast("수정된 내용이 없습니다.")
        return
    st.session_state[value_key] = current_form
    st.session_state[status_key] = "완료"
    # 일괄처리의 최초 결과는 일괄저장으로 반영하되, 이미 저장된 문장의
    # 재수정은 개별 완료 버튼으로 즉시 DB에 반영한다.
    should_save = (
        item.get("review_storage") == "add"
        or review_method != BATCH_REVIEW_METHOD
        or was_completed
    )
    if was_completed:
        st.session_state[review_widget_key("revised", modified_key)] = True
    if item and assignee and should_save:
        save_review_item(item, assignee, current_form, "완료")
    elif item and review_method == BATCH_REVIEW_METHOD:
        sentence_key = (item["data_version"], item["doc_id"], item["sentence_id"])
        st.session_state[review_widget_key("batch_pending", sentence_key)] = st.session_state.get("rule_filter_key")
        st.toast("수정완료로 표시했습니다. 현재 페이지 일괄저장을 눌러 DB에 반영해 주세요.")
        return
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
    if (
        item
        and assignee
        and review_method != BATCH_REVIEW_METHOD
        and item.get("review_storage") != "add"
    ):
        save_review_item(item, assignee, original_form, "완료")
    elif item and item.get("review_storage") != "add" and review_method == BATCH_REVIEW_METHOD:
        sentence_key = (item["data_version"], item["doc_id"], item["sentence_id"])
        st.session_state[review_widget_key("batch_pending", sentence_key)] = st.session_state.get("rule_filter_key")
        st.toast("이상없음으로 표시했습니다. 현재 페이지 일괄저장을 눌러 DB에 반영해 주세요.")
        return
    st.toast("이상없음으로 저장되었습니다.")


#---------------------------------------------------------------------------------------------------------
# 기능 - 배정 문장 검수 결과 저장
#---------------------------------------------------------------------------------------------------------
def save_review_page(review_updates, assignee, status_changed=True):
    """현재 페이지의 검수 결과를 ner_human_review에 저장한다."""
    query = """
        UPDATE public.ner_human_review
        SET modified_form = %s,
            review_status = %s,
            is_modified = %s,
            updated_at = CASE
                WHEN %s = '완료' THEN CURRENT_TIMESTAMP
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
    load_review_rows.clear()
    if status_changed:
        load_review_data.clear()
        fetch_review_entities.clear()


def save_review_item(item, assignee, modified_form, review_status):
    if item.get("review_storage") == "add":
        save_review_add_item(item, assignee, modified_form, review_status)
        return

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
        status_changed=item.get("review_status") != review_status,
    )


#---------------------------------------------------------------------------------------------------------
# 기능 - 추가 검수 문장 저장
#---------------------------------------------------------------------------------------------------------
def save_review_add_item(item, assignee, modified_form, review_status):
    query = """
        INSERT INTO public.ner_human_review_add (
            data_version, press, doc_id, sentence_id, original_form,
            modified_form, review_method, review_status, is_modified,
            assignee, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                CASE WHEN %s = '완료' THEN CURRENT_TIMESTAMP ELSE NULL END)
        ON CONFLICT (data_version, press, doc_id, sentence_id)
        DO UPDATE SET
            modified_form = EXCLUDED.modified_form,
            review_method = EXCLUDED.review_method,
            review_status = EXCLUDED.review_status,
            is_modified = EXCLUDED.is_modified,
            updated_at = EXCLUDED.updated_at
    """
    with get_postgre_connect() as conn:
        conn.execute(
            query,
            (
                item["data_version"],
                item["press"],
                item["doc_id"],
                item["sentence_id"],
                item.get("original_form") or "",
                modified_form,
                item.get("review_method") or "LLM검수",
                review_status,
                is_modified_form(modified_form, item.get("original_form")),
                assignee,
                review_status,
            ),
        )
    load_review_rows.clear()


#---------------------------------------------------------------------------------------------------------
# 기능 - 수정문 임시 상태 및 초안 저장
#---------------------------------------------------------------------------------------------------------
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
    if item.get("review_storage") == "add":
        return
    if is_modified_form(modified_form, item.get("original_form")):
        review_status = "미완료"
        st.session_state[status_key] = review_status
    save_review_item(item, assignee, modified_form, review_status)

#---------------------------------------------------------------------------------------------------------
# 데이터 조회 - 언론사별 데이터 버전
#---------------------------------------------------------------------------------------------------------
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


#---------------------------------------------------------------------------------------------------------
# 조회 조건 - 오류 유형 및 검수결과 필터
#---------------------------------------------------------------------------------------------------------
def rules_for_error_types(selected_types):
    return tuple(
        rule
        for group, rules in RULES_BY_TYPE.items()
        if RULE_GROUP_ERROR_TYPES[group] in selected_types
        for rule in rules
    )


def response_filter_condition(review_needed, review_status, selected_types):
    conditions = []
    params = []
    if review_needed != "전체":
        if review_needed == "미지정":
            conditions.append("v.review_needed IS NULL")
        else:
            conditions.append("v.review_needed = %s")
            params.append(review_needed == "필요")
    if review_status != "전체":
        if review_status is None:
            conditions.append("v.review_status IS NULL")
        else:
            conditions.append("v.review_status = %s")
            params.append(review_status)
    type_condition = "v.error_lv1 = ANY(%s)"
    params.append(list(selected_types))
    # 모든 유형을 선택한 경우에는 관리자용 판정 필터에서 정상 결과도 조회할 수 있다.
    if set(selected_types) == set(ERROR_TYPES):
        type_condition = f"({type_condition} OR v.review_status IS DISTINCT FROM 'error')"
    # 검증 실패 행은 오류 유형이 비어 있어도 같은 개체에서 검출된 룰로 찾을 수 있다.
    conditions.append(f"""({type_condition} OR (v.validation_failed AND EXISTS (
        SELECT 1 FROM candidate_rules AS r
        WHERE r.data_version = v.data_version AND r.doc_id = v.doc_id
          AND r.sentence_id = v.sentence_id
          AND (r.entity_id = v.entity_id OR r.entity_id IS NULL)
    )))""")
    return " AND ".join(conditions), params


#---------------------------------------------------------------------------------------------------------
# 조회 조건 - 검수결과와 검출 룰 연결
#---------------------------------------------------------------------------------------------------------
def review_filter_ctes(press, data_versions, selected_types, review_needed, review_status, doc_id=None):
    """목록·본문·참고 정보에 같은 조건을 적용하고, 같은 개체의 검수결과를 우선한다."""
    selected_rules = rules_for_error_types(selected_types)
    rule_condition = " OR ".join(f'r."{rule}" IS TRUE' for rule in selected_rules) or "FALSE"
    response_condition, response_params = response_filter_condition(
        review_needed, review_status, selected_types
    )
    params = [list(data_versions), press]
    response_doc_condition = ""
    rule_doc_condition = ""
    if doc_id is not None:
        response_doc_condition = "AND v.doc_id = %s"
        rule_doc_condition = "AND r.doc_id = %s"
        params.append(doc_id)
    params.extend([list(data_versions), press])
    if doc_id is not None:
        params.append(doc_id)
    params.extend(response_params)
    validation_failed = "COALESCE(STRPOS(v.reason, '[자동검증 실패]'), 0) > 0"
    allow_rule_fallback = review_needed == "전체" and review_status in ("전체", "error")
    query = f"""
        review_source AS (
            SELECT run.data_version, SPLIT_PART(v.run_id, '_', 7) AS press,
                   v.run_id, v.doc_id, v.sentence_id, v.entity_id,
                   v.target_span, v.target_type, v.corrected_span,
                   CASE WHEN v.review_status = 'error'
                        THEN COALESCE(NULLIF(BTRIM(v.error_lv1), ''), 'etc')
                        ELSE NULLIF(BTRIM(v.error_lv1), '') END AS error_lv1,
                   v.error_lv2, v.reason, v.review_needed, v.review_status,
                   {validation_failed} AS validation_failed
            FROM public.ner_reviews AS v
            JOIN public.ner_runs AS run ON run.run_id = v.run_id
            WHERE run.data_version = ANY(%s)
              AND SPLIT_PART(v.run_id, '_', 7) = %s
              AND (v.entity_id IS NOT NULL OR {validation_failed})
              {response_doc_condition}
        ), candidate_rules AS NOT MATERIALIZED (
            SELECT r.* FROM public.ner_rule_results_3 AS r
            WHERE r.data_version = ANY(%s)
              AND regexp_replace(r.data_version, '^.*_', '') = %s
              {rule_doc_condition}
              AND ({rule_condition})
        ), filtered_responses AS (
            SELECT v.* FROM review_source AS v
            WHERE {response_condition}
        ), matched_rules AS (
            SELECT r.*, (
                SELECT CASE WHEN NOT BOOL_OR(v.validation_failed)
                            THEN ARRAY_AGG(DISTINCT v.error_lv1) END
                FROM filtered_responses AS v
                WHERE v.data_version = r.data_version
                  AND v.doc_id = r.doc_id AND v.sentence_id = r.sentence_id
                  AND (v.entity_id = r.entity_id OR r.entity_id IS NULL)
            ) AS response_error_types
            FROM candidate_rules AS r
            WHERE (
                  EXISTS (
                      SELECT 1 FROM filtered_responses AS v
                      WHERE v.data_version = r.data_version
                        AND v.doc_id = r.doc_id AND v.sentence_id = r.sentence_id
                        AND (v.entity_id = r.entity_id OR r.entity_id IS NULL)
                  )
                  OR ({'TRUE' if allow_rule_fallback else 'FALSE'} AND NOT EXISTS (
                      SELECT 1 FROM review_source AS v
                      WHERE v.data_version = r.data_version
                        AND v.doc_id = r.doc_id AND v.sentence_id = r.sentence_id
                        AND (v.entity_id = r.entity_id OR r.entity_id IS NULL)
                  ))
              )
        )
    """
    return query, params


#---------------------------------------------------------------------------------------------------------
# 데이터 조회 - 검수 판정 및 문장별 참고 정보
#---------------------------------------------------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_response_statuses(press, data_versions):
    with get_postgre_connect() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT v.review_status
            FROM public.ner_reviews AS v
            JOIN public.ner_runs AS run ON run.run_id = v.run_id
            WHERE v.entity_id IS NOT NULL
              AND SPLIT_PART(v.run_id, '_', 7) = %s
              AND run.data_version = ANY(%s)
            ORDER BY v.review_status NULLS LAST
            """,
            (press, data_versions),
        ).fetchall()
    return [row["review_status"] for row in rows]


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_response_results(data_version, press, doc_id, review_needed, review_status, selected_types):
    filter_ctes, params = review_filter_ctes(
        press, [data_version], selected_types, review_needed, review_status, doc_id
    )
    with get_postgre_connect() as conn:
        rows = conn.execute(
            f"""
            WITH {filter_ctes}
            SELECT v.run_id, v.press,
                   v.doc_id, v.sentence_id, v.entity_id,
                   v.target_span, v.target_type, v.corrected_span,
                   v.error_lv1, v.error_lv2, v.reason,
                   v.review_needed, v.review_status, v.validation_failed
            FROM filtered_responses AS v
            ORDER BY v.sentence_id, v.entity_id, v.run_id DESC
            """,
            params,
        ).fetchall()
    results = {}
    for row in rows:
        if row["validation_failed"]:
            row.update(reason=None, corrected_span=None, error_lv1=None, error_lv2=None)
        else:
            reason = re.sub(r"\[자동(?:검증|점검):[^\]\r\n]*\]\s*", "", row["reason"] or "")
            row["reason"] = re.sub(
                r"(?<![A-Za-z0-9_])(?:LLM|AI)(?![A-Za-z0-9_])(?:[ \t]*검수)?",
                "검수", reason, flags=re.IGNORECASE,
            ).strip()
        results.setdefault(row["sentence_id"], []).append(row)
    return results


#---------------------------------------------------------------------------------------------------------
# 조회 조건 - 배정 기사 및 기사 완료 상태
#---------------------------------------------------------------------------------------------------------
def review_list_ctes(
    selected_press,
    data_versions,
    selected_types,
    review_method=None,
    assignee=None,
    search_text="",
    response_review_needed="전체",
    response_review_status="전체",
    completion_status="전체",
    retained_doc_id=None,
):
    """기사 목록과 개체 선택 목록에 동일한 배정·검수 조건을 적용한다."""
    result_filter = response_review_status if response_review_status in ("error", "normal") else "전체"
    filter_ctes, params = review_filter_ctes(
        selected_press, data_versions, selected_types, response_review_needed, result_filter,
    )
    params.extend([selected_press, list(data_versions), None])
    category = []
    if review_method == HUMAN_REVIEW_METHOD:
        category.append("""((ra.final_result = 'error' AND s.human_error)
                         OR (ra.final_result = 'normal' AND s.rule_detected))""")
        if response_review_status != "전체":
            category.append("ra.final_result = %s")
            params.append("error" if response_review_status == "error" else "normal")
    elif review_method:
        category.append("s.review_method = %s")
        params.append(review_method)

    # 검색·오류유형·개체 필터로 숨겨진 문장까지 포함해 기사 완료 여부를 판단한다.
    params.append(assignee)
    filters = ["s.assignee = %s"]
    params.append(assignee)
    if completion_status != "전체":
        filters.append("(a.article_completed = %s OR s.doc_id = %s)")
        params.extend([completion_status == "완료", retained_doc_id])
    if search_text.strip():
        filters.append("(s.doc_id ILIKE %s OR s.sentence_id ILIKE %s)")
        params.extend([f"%{search_text.strip()}%"] * 2)
    if set(selected_types) != set(ERROR_TYPES):
        same_sentence = "t.data_version = s.data_version AND t.doc_id = s.doc_id AND t.sentence_id = s.sentence_id"
        rule_match = f"EXISTS (SELECT 1 FROM candidate_rules t WHERE {same_sentence})"
        if review_method == HUMAN_REVIEW_METHOD:
            error_match = f"EXISTS (SELECT 1 FROM filtered_responses t WHERE {same_sentence} AND t.review_status = 'error')"
            filters.append(f"((s.final_result = 'error' AND {error_match}) OR (s.final_result = 'normal' AND {rule_match}))")
        else:
            filters.append(rule_match)
    query = f"""
        {filter_ctes}, {REVIEW_SCOPE_CTES}, eligible AS (
            SELECT s.*, a.article_result, ra.final_result FROM review_sentences s
            LEFT JOIN rule_articles ra USING (press, doc_id)
            LEFT JOIN human_articles a ON a.press = s.press AND a.doc_id = s.doc_id
                                      AND s.review_method = 'LLM검수'
            WHERE {" AND ".join(category) or "TRUE"}
        ), assigned_article_status AS (
            SELECT press, doc_id,
                   BOOL_AND(review_status IS NOT DISTINCT FROM '완료') AS article_completed
            FROM eligible WHERE assignee = %s
            GROUP BY press, doc_id
        ), filtered AS (
            SELECT s.*, a.article_completed FROM eligible s
            JOIN assigned_article_status a USING (press, doc_id)
            WHERE {" AND ".join(filters)}
        )
    """
    return query, params


#---------------------------------------------------------------------------------------------------------
# 데이터 조회 - 검수 대상 개체 목록 및 선택
#---------------------------------------------------------------------------------------------------------
@st.cache_data(ttl=900, max_entries=64, show_spinner=False)
def fetch_review_entities(
    selected_press, data_versions, selected_types, review_method, assignee,
    search_text, response_review_needed, response_review_status,
    completion_status="전체",
    entity_search="", frequent_first=True, after=None,
):
    """전체 빈도를 재집계하지 않고 내 검수대상에 출현하는 개체 쌍을 30개씩 찾는다."""
    scope_ctes, params = review_list_ctes(
        selected_press, data_versions, selected_types, review_method, assignee,
        search_text, response_review_needed, response_review_status,
        completion_status,
    )
    conditions = []
    location_condition = "TRUE"
    if entity_search.strip():
        location_condition = "(l.entity_name ILIKE %s OR l.entity_type ILIKE %s)"
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
                WITH {scope_ctes}, scoped_entities AS MATERIALIZED (
                    SELECT DISTINCT l.entity_name, l.entity_type
                    FROM (SELECT DISTINCT doc_id, sentence_id FROM filtered) s
                    JOIN public.ner_entity_location l
                      ON l.doc_id = s.doc_id AND l.sentence_id = s.sentence_id
                    WHERE {location_condition}
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


def select_review_entity(scope_args, key_prefix):
    return render_entity_filter(
        scope_args,
        lambda term, frequent_first, after: fetch_review_entities(*scope_args, term, frequent_first, after),
        key_prefix,
    )


#---------------------------------------------------------------------------------------------------------
# 데이터 조회 - 조건별 검수 기사 및 대상 문장
#---------------------------------------------------------------------------------------------------------
def fetch_rule_results(
    selected_press, data_versions, selected_types, limit, offset,
    review_method=None, assignee=None, search_text="",
    response_review_needed="전체", response_review_status="전체", selected_entity=None,
    completion_status="전체", retained_doc_id=None,
):
    """개체 선택은 기사에만 적용하고 해당 기사의 다른 검수대상 문장도 유지한다."""
    selected_rules = rules_for_error_types(selected_types)
    scope_ctes, params = review_list_ctes(
        selected_press, data_versions, selected_types, review_method, assignee,
        search_text, response_review_needed, response_review_status,
        completion_status, retained_doc_id,
    )
    entity_condition = "TRUE"
    if selected_entity is not None:
        entity_condition = """EXISTS (
            SELECT 1 FROM public.ner_entity_location l
            WHERE l.doc_id = s.doc_id AND l.sentence_id = s.sentence_id
              AND l.entity_name = %s AND l.entity_type = %s
        )"""
        params.extend(selected_entity)
    params.extend([limit, offset, retained_doc_id])
    rule_source = "matched_rules" if review_method == HUMAN_REVIEW_METHOD else "candidate_rules"
    rule_types = "r.response_error_types" if rule_source == "matched_rules" else "NULL::text[]"
    rule_columns = [
        f'r."{column}"' for rule in selected_rules
        for column in ([rule] if rule == "EXT_S003" else [rule, f"{rule}_PATTERN"])
    ]
    if review_method == HUMAN_REVIEW_METHOD:
        press_counts = """SELECT COUNT(*) AS press_article_count,
                                 COUNT(*) FILTER (WHERE final_result = 'error') AS final_errors
                          FROM rule_articles"""
    else:
        press_counts = "SELECT COUNT(DISTINCT doc_id) AS press_article_count, 0 AS final_errors FROM eligible"
    query = f"""
        WITH {scope_ctes}, filtered_docs AS (
            SELECT DISTINCT s.doc_id FROM filtered s WHERE {entity_condition}
        ), page_docs AS (
            SELECT doc_id FROM (
                SELECT doc_id FROM filtered_docs
                ORDER BY SUBSTRING(doc_id FROM '(?:^|[.])([0-9]+)$')::numeric NULLS LAST, doc_id
                LIMIT %s OFFSET %s
            ) current_page
            UNION
            SELECT doc_id FROM filtered_docs WHERE doc_id = %s
        ), counts AS (
            {press_counts}
        ), page_rows AS (
            SELECT s.*, h.original_form, h.modified_form, h.is_modified,
                   r.entity_id, r.entity_tagging, {rule_types} AS response_error_types,
                   d.detected_entities, d.candidate_rule_ids, d.tagging_error_result, d.tagging_merge_result
                   {"," + ", ".join(rule_columns) if rule_columns else ""}
            FROM page_docs p JOIN filtered s USING (doc_id)
            JOIN public.ner_human_review h USING (data_version, press, doc_id, sentence_id)
            LEFT JOIN {rule_source} r ON r.data_version = s.data_version
              AND r.doc_id = s.doc_id AND r.sentence_id = s.sentence_id
            LEFT JOIN public.ner_decision_results d ON d.data_version = s.data_version AND d.press = s.press
              AND d.doc_id = s.doc_id AND d.sentence_id = s.sentence_id
        )
        SELECT p.*, c.*, (SELECT COUNT(*) FROM filtered_docs) AS filtered_article_count
        FROM counts c LEFT JOIN page_rows p ON TRUE
        ORDER BY p.doc_id, p.data_version, p.sentence_id, p.entity_id
    """
    rows = load_review_rows(query, params)
    return ([row for row in rows if row["doc_id"] is not None],
            rows[0]["filtered_article_count"], rows[0]["press_article_count"], rows[0]["final_errors"])


#---------------------------------------------------------------------------------------------------------
# 기능 - 현재 조회 조건에서 다음 기사 선택
#---------------------------------------------------------------------------------------------------------
def select_next_review_article(scope_args, selected_entity, current_doc_id, position, filter_prefix, filter_key):
    scope_ctes, params = review_list_ctes(*scope_args)
    entity_condition = "TRUE"
    if selected_entity is not None:
        entity_condition = """EXISTS (
            SELECT 1 FROM public.ner_entity_location l
            WHERE l.doc_id = s.doc_id AND l.sentence_id = s.sentence_id
              AND l.entity_name = %s AND l.entity_type = %s
        )"""
        params.extend(selected_entity)
    params.extend([current_doc_id, current_doc_id])
    query = f"""
        WITH {scope_ctes}, matching_docs AS (
            SELECT DISTINCT s.doc_id FROM filtered s WHERE {entity_condition}
        ), ordered_docs AS (
            SELECT doc_id,
                   COALESCE(SUBSTRING(doc_id FROM '(?:^|[.])([0-9]+)$')::numeric,
                            'Infinity'::numeric) AS sort_number,
                   ROW_NUMBER() OVER (
                       ORDER BY SUBSTRING(doc_id FROM '(?:^|[.])([0-9]+)$')::numeric NULLS LAST, doc_id
                   ) - 1 AS article_offset
            FROM matching_docs
        )
        SELECT doc_id, article_offset FROM ordered_docs
        WHERE (sort_number, doc_id) > (
            COALESCE(SUBSTRING(%s::text FROM '(?:^|[.])([0-9]+)$')::numeric, 'Infinity'::numeric), %s
        )
        ORDER BY sort_number, doc_id LIMIT 1
    """
    with get_postgre_connect() as conn:
        next_article = conn.execute(query, params).fetchone()
    if next_article is None:
        st.toast("현재 조회 조건에서 다음 기사가 없습니다.")
        return
    next_offset = int(next_article["article_offset"]) // PAGE_SIZE * PAGE_SIZE
    next_id = next_article["doc_id"]
    position.update(offset=next_offset, active_doc_id=next_id, active_page=next_offset)
    position.setdefault("selections", {})[next_offset] = {"doc_id": next_id, "index": 0}
    next_key = filter_prefix + "_doc_" + hashlib.md5(f"{filter_key}|{next_offset}".encode("utf-8")).hexdigest()
    st.session_state[next_key] = next_id


#---------------------------------------------------------------------------------------------------------
# 데이터 조회 - 선택 기사의 전체 문장
#---------------------------------------------------------------------------------------------------------
def fetch_article_sentences(
    data_version,
    doc_id,
    press,
    assignee,
    selected_review_method,
    selected_types,
    response_review_needed,
    response_review_status,
):
    """선택한 기사의 전체 문장과 검증 실패 시 참고할 룰을 조회한다."""
    selected_rules = rules_for_error_types(selected_types)
    filter_ctes, filter_params = review_filter_ctes(
        press, [data_version], selected_types,
        response_review_needed, response_review_status, doc_id,
    )
    rule_condition = " OR ".join(f'r."{rule}" IS TRUE' for rule in selected_rules)
    rule_join = ""
    rule_columns = [
        "NULL AS entity_id", "NULL AS entity_tagging", "NULL AS response_error_types"
    ]
    if selected_rules:
        rule_source = "matched_rules" if selected_review_method == HUMAN_REVIEW_METHOD else "candidate_rules"
        rule_join = f"""
        LEFT JOIN {rule_source} AS r
          ON r.data_version = target.data_version
         AND r.doc_id = n.doc_id
         AND r.sentence_id = n.sentence_id
         AND ({rule_condition})
        """
        rule_columns = ["r.entity_id", "r.entity_tagging",
                        "r.response_error_types" if rule_source == "matched_rules" else "NULL AS response_error_types"]

    selected_rule_columns = ",\n            ".join(
        column
        for rule in selected_rules
        for column in (
            [f'r."{rule}"']
            if rule == "EXT_S003"
            else [f'r."{rule}"', f'r."{rule}_PATTERN"']
        )
    )
    if not selected_rule_columns:
        selected_rule_columns = "NULL AS rule_result_placeholder"

    entity_order = ", r.entity_id" if selected_rules else ""

    query = f"""
        WITH {filter_ctes}, {REVIEW_SCOPE_CTES}, target AS (
            SELECT
                %s::TEXT AS data_version,
                %s::TEXT AS press,
                %s::TEXT AS assignee,
                %s::TEXT AS doc_id,
                %s::TEXT AS selected_review_method
        )
        SELECT
            target.data_version AS data_version,
            target.press AS press,
            n.doc_id AS doc_id,
            n.sentence_id AS sentence_id,
            n.form AS document_original_form,
            COALESCE(h.original_form, n.form) AS original_form,
            COALESCE(h.modified_form, n.form) AS modified_form,
            COALESCE(
                h.review_method,
                a.review_method,
                target.selected_review_method,
                (
                    SELECT MIN(h0.review_method)
                    FROM public.ner_human_review AS h0
                    WHERE h0.data_version = target.data_version
                      AND h0.press = target.press
                      AND h0.doc_id = n.doc_id
                      AND h0.assignee = target.assignee
                )
            ) AS review_method,
            COALESCE(h.review_status, a.review_status) AS review_status,
            COALESCE(h.is_modified, a.is_modified, FALSE) AS is_modified,
            CASE WHEN h.sentence_id IS NULL THEN 'add' ELSE 'human' END AS review_storage,
            CASE WHEN h.sentence_id IS NULL THEN 'N' ELSE 'Y' END AS review_target,
            s.sentence_result, s.rule_detected,
            d.detected_entities,
            d.candidate_rule_ids,
            d.tagging_error_result,
            d.tagging_merge_result,
            {", ".join(rule_columns)},
            {selected_rule_columns}
        FROM target
        JOIN public.ner_documents AS n
          ON n.doc_id = target.doc_id
        LEFT JOIN public.ner_human_review AS h
          ON h.data_version = target.data_version
         AND h.press = target.press
         AND h.doc_id = n.doc_id
         AND h.sentence_id = n.sentence_id
         AND h.assignee = target.assignee
        LEFT JOIN review_sentences s
          ON s.data_version = h.data_version AND s.press = h.press
         AND s.doc_id = h.doc_id AND s.sentence_id = h.sentence_id
        LEFT JOIN public.ner_human_review_add AS a
          ON a.data_version = target.data_version
         AND a.press = target.press
         AND a.doc_id = n.doc_id
         AND a.sentence_id = n.sentence_id
        LEFT JOIN public.ner_decision_results AS d
          ON d.data_version = target.data_version
         AND d.press = target.press
         AND d.doc_id = n.doc_id
         AND d.sentence_id = n.sentence_id
        {rule_join}
        ORDER BY n.sentence_id{entity_order}
    """

    return load_review_rows(
        query,
        (*filter_params, press, [data_version], doc_id, data_version, press, assignee, doc_id, selected_review_method),
    )


#---------------------------------------------------------------------------------------------------------
# 데이터 가공 - 문장별 검출 룰 및 판정 묶음
#---------------------------------------------------------------------------------------------------------
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
                "sentence_result": row.get("sentence_result"),
                "article_result": row.get("article_result"),
                "final_result": row.get("final_result"),
                "rule_detected": row.get("rule_detected"),
                "review_status": row.get("review_status"),
                "review_storage": row.get("review_storage") or "human",
                "review_target": row.get("review_target") or "Y",
                "is_modified": row.get("is_modified", False),
                "tags": set(),
                "matches": set(),
                "matches_by_entity": {},
                "decision": {
                    "detected_entities": row.get("detected_entities"),
                    "candidate_rule_ids": row.get("candidate_rule_ids"),
                    "tagging_error_result": row.get("tagging_error_result"),
                    "tagging_merge_result": row.get("tagging_merge_result"),
                },
            },
        )

        if row.get("entity_tagging"):
            item["tags"].add(row["entity_tagging"])

        for rule in selected_rules:
            response_error_types = row.get("response_error_types")
            if response_error_types is not None and RULE_ERROR_TYPES[rule] not in response_error_types:
                continue
            if row.get(rule):
                pattern = row.get(f"{rule}_PATTERN")
                match = (rule, pattern or "패턴 없음")
                item["matches"].add(match)
                item["matches_by_entity"].setdefault(row["entity_id"], set()).add(match)

    return grouped


#---------------------------------------------------------------------------------------------------------
# 기능 - 의심도 및 상세 판정 표시 기준
#---------------------------------------------------------------------------------------------------------
def has_decision_result(decision):
    return any(value not in (None, "", [], {}, ()) for value in decision.values())


SUSPICION_COLORS = {
    "약한 의심": "#94A3B8",
    "중간 의심": "#F59E0B",
    "강한 의심": "#EF4444",
}
SUSPICION_PRIORITY = {"약한 의심": 1, "중간 의심": 2, "강한 의심": 3}
SUSPICION_LABELS = {
    "약한 의심": "낮음",
    "중간 의심": "중간",
    "강한 의심": "높음",
}


def normalize_suspicion_level(value):
    value = str(value).strip()
    return value if value in SUSPICION_COLORS else None


#---------------------------------------------------------------------------------------------------------
# 기능 - 오류 유형별 상세 판정 및 강조 구간
#---------------------------------------------------------------------------------------------------------
def filter_decision_types(decision, selected_types):
    filtered = {
        key: decision.get(key)
        for error_type, key in (
            ("tagging_error", "tagging_error_result"),
            ("span_error", "tagging_merge_result"),
        )
        if error_type in selected_types
        and normalize_suspicion_level(decision.get(key))
    }
    if filtered:
        filtered["detected_entities"] = decision.get("detected_entities")
    return filtered


def get_decision_highlights(decision):
    entities = [
        entity.strip()
        for entity in str(decision.get("detected_entities") or "").split(",")
        if entity.strip()
    ]
    levels = [
        level
        for level in (
            decision.get("tagging_error_result"),
            decision.get("tagging_merge_result"),
        )
        if normalize_suspicion_level(level)
    ]
    levels = [normalize_suspicion_level(level) for level in levels]
    level = max(levels, key=SUSPICION_PRIORITY.get) if levels else None
    return [(entity, level) for entity in entities if level]


#---------------------------------------------------------------------------------------------------------
# 화면 구성 - 검출 룰과 수정 제안의 원문 강조
#---------------------------------------------------------------------------------------------------------
def highlighted_form_with_decision(form, matches, decision_highlights, references=(), show_rule_patterns=False):
    """검수 대상 우선 강조에 기존 의심 밑줄과 수정 제안 테두리를 함께 표시한다."""
    form = form or ""
    if not references and not decision_highlights:
        return highlighted_form(form, matches)

    annotations = [
        (*match.span(), level)
        for entity, level in decision_highlights
        for match in re.finditer(re.escape(entity), form)
    ]
    if not references or show_rule_patterns:
        patterns = {
            part.strip()
            for _, pattern in matches if pattern != "패턴 없음"
            for part in re.split(r",\s*|\r?\n", str(pattern)) if part.strip()
        }
        for pattern in patterns:
            annotations.extend(
                (*match.span(), None)
                for match in re.finditer(re.escape(pattern), form)
            )

    targets = [
        (start, end, number)
        for number, reference in enumerate(references, 1)
        for start, end in sorted(reference["positions"])
    ]
    # 테두리는 검수 구간의 양끝에서만 나눈다. 의심도 밑줄은 그 안에서 따로 그린다.
    boundaries = sorted({0, len(form)} | {p for start, end, _ in targets for p in (start, end)})
    rendered = []
    for start, end in zip(boundaries, boundaries[1:]):
        active = [(a, b, level) for a, b, level in annotations if a < end and start < b]
        inner = sorted({start, end} | {p for a, b, _ in active for p in (a, b) if start < p < end})
        pieces = []
        for left, right in zip(inner, inner[1:]):
            levels = {level for a, b, level in active if a < right and left < b}
            styles = ["background-color:#ffe08a"] if None in levels else []
            level = max(levels - {None}, key=SUSPICION_PRIORITY.get, default=None)
            if level:
                styles.append(f"text-decoration:underline 3px {SUSPICION_COLORS[level]};text-underline-offset:3px")
            text = html.escape(form[left:right])
            pieces.append(f'<span style="{";".join(styles)}">{text}</span>' if styles else text)
        content = "".join(pieces)
        covering = [(a, b, n) for a, b, n in targets if a < end and start < b]
        if covering:
            numbers = sorted({n for _, _, n in covering})
            starts = sorted({n for a, _, n in covering if a == start})
            ends = sorted({n for _, b, n in covering if b == end})
            proposals = {
                n: references[n - 1]["corrected_span"] for n in numbers
                if references[n - 1]["corrected_span"] not in (None, references[n - 1]["target_span"])
            }
            styles = ["background-color:#ffe08a"]
            tooltip = ""
            if proposals:
                styles.append("border-block:1px dashed #0F766E")
                if proposals.keys() & set(starts):
                    styles.append("border-inline-start:1px dashed #0F766E")
                if proposals.keys() & set(ends):
                    styles.append("border-inline-end:1px dashed #0F766E")
                suggestions = " / ".join(dict.fromkeys(value or "삭제" for value in proposals.values()))
                tooltip = f' title="수정 제안: {html.escape(suggestions)}"'
            labels = "".join(f'<sup class="review-target-number">{n}</sup>' for n in starts)
            rendered.append(
                f'<span data-review-target="{" ".join(map(str, numbers))}" '
                f'data-review-start="{" ".join(map(str, starts))}" data-review-end="{" ".join(map(str, ends))}" '
                f'style="{";".join(styles)}"{tooltip}>{labels}{content}</span>'
            )
        else:
            rendered.append(content)

    return (
        '<div style="white-space:pre-wrap; line-height:1.9; '
        f'font-size:16px">{"".join(rendered)}</div>'
    )

#---------------------------------------------------------------------------------------------------------
# 화면 구성 - 검출 패턴 강조
#---------------------------------------------------------------------------------------------------------
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

#---------------------------------------------------------------------------------------------------------
# 기능 - 문장 표시 명칭 및 기사 정렬 기준
#---------------------------------------------------------------------------------------------------------
def sentence_label(sentence_key, grouped):
    item = grouped[sentence_key]
    sentence_id = item["sentence_id"]
    form = " ".join(item["original_form"].split())
    preview = form[:34] + ("…" if len(form) > 34 else "")
    return f"{sentence_id}  ·  {preview}" if preview else sentence_id


def document_sort_key(doc_id):
    """문서 ID가 숫자 접미사를 갖지 않아도 정렬 가능하도록 한다."""
    suffix = doc_id.rsplit(".", 1)[-1]
    if suffix.isascii() and suffix.isdigit():
        return 0, int(suffix), doc_id
    return 1, 0, doc_id


def sentence_sort_key(sentence_key):
    """문장 ID를 점(.)으로 나눈 숫자 구간 기준으로 정렬한다."""
    data_version, doc_id, sentence_id = sentence_key
    sentence_id = str(sentence_id)
    parts = []
    for part in sentence_id.split("."):
        if part.isdigit():
            parts.append((0, int(part)))
        else:
            parts.append((1, part))
    return data_version, doc_id, tuple(parts), sentence_id

#---------------------------------------------------------------------------------------------------------
# 데이터 조회
#---------------------------------------------------------------------------------------------------------
authenticated_assignee = authenticate_reviewer()
show_detailed_review = authenticated_assignee == "김소희"
ner_header_placeholder = st.empty()
page_review_method = globals().get("REVIEW_PAGE_METHOD", HUMAN_REVIEW_METHOD)
article_state = get_article_list_state(("review", page_review_method, authenticated_assignee))
filter_prefix = "review_" + hashlib.md5(
    repr((page_review_method, authenticated_assignee)).encode("utf-8")
).hexdigest()
press_widget_key = f"{filter_prefix}_press"
search_widget_key = f"{filter_prefix}_search"
response_status_widget_key = f"{filter_prefix}_response_status"
completion_widget_key = f"{filter_prefix}_completion"
error_type_prefix = f"{filter_prefix}_error_type"
entity_filter_prefix = f"{filter_prefix}_entity"

try:
    requested_press = st.query_params.get("press")
    press_versions = fetch_press_versions()

except Exception as exc:
    st.error(f"데이터 조회 실패: {exc}")
    st.stop()

if not press_versions:
    st.info("조회 가능한 데이터가 없습니다.")
    st.stop()
    
#---------------------------------------------------------------------------------------------------------
# 다중 선택 드롭다운
#---------------------------------------------------------------------------------------------------------
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

#---------------------------------------------------------------------------------------------------------
# 좌측 사이드바 - 필터
#---------------------------------------------------------------------------------------------------------
press_options = sorted(press_versions)
if requested_press in press_options:
    st.session_state[press_widget_key] = requested_press
elif st.session_state.get(press_widget_key) not in press_options:
    st.session_state[press_widget_key] = press_options[0]

search_text = st.sidebar.text_input(
    "기사ID 또는 문장ID 검색",
    key=search_widget_key,
    placeholder="기사ID 또는 문장ID 검색",
    label_visibility="collapsed"
).strip()

with st.sidebar.popover(f"언론사 ({st.session_state[press_widget_key]})", width="stretch"):
    selected_press = st.radio(
        "언론사 선택",
        press_options,
        key=press_widget_key,
        label_visibility="collapsed",
    )

selected_press = st.session_state[press_widget_key]

selected_review_method = page_review_method
selected_review_method_display = METHOD_DISPLAY_NAMES[selected_review_method]

response_review_needed = "전체"
#---------------------------------------------------------------------------------------------------------
# 사이드바 - 휴먼검수 판정 필터
#---------------------------------------------------------------------------------------------------------
response_review_status = "전체"
scope_label = selected_review_method_display
if selected_review_method == HUMAN_REVIEW_METHOD:
    status_labels = {
        "전체": "전체",
        "error": "오류",
        "final_normal": "정상",
    }
    if st.session_state.get(response_status_widget_key) not in status_labels:
        st.session_state[response_status_widget_key] = "전체"
    response_status_label = status_labels[st.session_state[response_status_widget_key]]
    with st.sidebar.popover(f"검수결과 ({response_status_label})", width="stretch"):
        response_review_status = st.radio(
            "검수판정",
            list(status_labels),
            format_func=status_labels.get,
            key=response_status_widget_key,
            label_visibility="collapsed",
        )
    scope_label = f"{selected_review_method_display} · {status_labels[response_review_status]}"

#---------------------------------------------------------------------------------------------------------
# 사이드바 - 검수 상태 및 오류 유형 필터
#---------------------------------------------------------------------------------------------------------
completion_options = ["전체", "미완료", "완료"]
if st.session_state.get(completion_widget_key) not in completion_options:
    st.session_state[completion_widget_key] = "전체"
with st.sidebar.popover(f"검수상태 ({st.session_state[completion_widget_key]})", width="stretch"):
    completion_status = st.radio("검수 상태 선택", completion_options, key=completion_widget_key, label_visibility="collapsed")

filter_by_type = selected_review_method in (HUMAN_REVIEW_METHOD, BATCH_REVIEW_METHOD)
selected_types = ERROR_TYPES
if filter_by_type:
    selected_types = multi_select_filter("오류유형", ERROR_TYPES, ERROR_TYPES, ERROR_TYPE_NAMES.get, error_type_prefix)
selected_rules = rules_for_error_types(selected_types)

#---------------------------------------------------------------------------------------------------------
# 사이드바 - 우선 검수 개체 선택
#---------------------------------------------------------------------------------------------------------
priority_entity = select_review_entity((
    selected_press, tuple(press_versions[selected_press]), selected_types,
    selected_review_method, authenticated_assignee, search_text,
    response_review_needed, response_review_status, completion_status,
), entity_filter_prefix)
selected_entity = (
    (priority_entity["entity_name"], priority_entity["entity_type"])
    if priority_entity else None
)
remember_article_filters(article_state, [
    press_widget_key, search_widget_key, response_status_widget_key, completion_widget_key,
    *(f"{error_type_prefix}_{error_type}" for error_type in ERROR_TYPES),
    *(f"{entity_filter_prefix}_{suffix}" for suffix in ("enabled", "name", "order")),
])

with ner_header_placeholder.container(border=False):
    selected_type_names = [
        ERROR_TYPE_NAMES[value]
        for value in selected_types
    ]
    selected_type_display = (
        "  ".join(
            f'''<span style="
                color:#64748b;
                background-color:#f1f5f9;
                border-radius:4px;
                padding:2px 6px;
                font-size:11px;
                font-weight:400;
            ">{html.escape(rule_name)}</span>'''
            for rule_name, _ in zip(selected_type_names, selected_types)
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
        <div class="ner-info"><strong>조회대상</strong> : <span>{scope_label}</span></div>
        {('<div class="ner-info"><strong>오류유형</strong> : <span>' + selected_type_display + '</span></div>') if filter_by_type else ''}
        """,
        unsafe_allow_html=True,
    )

filter_key = (
    authenticated_assignee,
    selected_press,
    selected_review_method_display,
    selected_types,
#---------------------------------------------------------------------------------------------------------
# 화면 설정 - 조회 조건별 페이지 위치 및 사이드바 서식
#---------------------------------------------------------------------------------------------------------
    selected_rules,
    search_text,
    response_review_needed,
    response_review_status,
    selected_entity,
    completion_status,
)

st.session_state["rule_filter_key"] = filter_key
position = article_state["positions"].setdefault(filter_key, {"offset": 0})
offset = position["offset"]
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

#---------------------------------------------------------------------------------------------------------
# 선택 조건에 해당하는 문장 조회
#---------------------------------------------------------------------------------------------------------
try:
    rows, filtered_article_count, press_article_count, final_errors = fetch_rule_results(
        selected_press,
        press_versions[selected_press],
        selected_types,
        PAGE_SIZE,
        offset,
        selected_review_method,
        authenticated_assignee,
        search_text,
        response_review_needed,
        response_review_status,
        selected_entity,
        completion_status,
        position.get("active_doc_id") if position.get("active_page") == offset else None,
    )
except Exception as exc:
    st.error(f"검수 기사 조회 실패: {exc}")
    st.stop()

grouped = group_sentences(rows, selected_rules)

#---------------------------------------------------------------------------------------------------------
# 데이터 가공 - 기사별 문장 및 데이터 버전 구성
#---------------------------------------------------------------------------------------------------------
# 조회 결과를 기사별로 묶기
docs = {}
for sentence_key, item in grouped.items():
    doc_key = (item["data_version"], item["doc_id"])
    docs.setdefault(doc_key, []).append(sentence_key)

versions_by_doc = {}
for version, doc_id in sorted(docs):
    versions_by_doc.setdefault(doc_id, []).append(version)
page_doc_ids = sorted(versions_by_doc, key=document_sort_key)
has_next = offset + len(page_doc_ids) < filtered_article_count
if offset and not page_doc_ids:
    position["offset"] = max(0, (filtered_article_count - 1) // PAGE_SIZE * PAGE_SIZE)
    st.rerun()

#---------------------------------------------------------------------------------------------------------
# 화면 상태 - 현재 페이지 문장의 검수 상태 복원
#---------------------------------------------------------------------------------------------------------
# 현재 페이지에 실제 표시되는 문장의 임시 검수 상태와 수정문을 초기화한다.
visible_sentence_keys = [
    sentence_key
    for doc_key in docs
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

#---------------------------------------------------------------------------------------------------------
# 좌측 사이드바 - 검수 기사 목록 및 페이지 이동
#---------------------------------------------------------------------------------------------------------
page_sentence_keys = visible_sentence_keys
all_page_completed = bool(page_sentence_keys) and all(
    st.session_state.get(review_widget_key("review_status", sentence_key)) == "완료"
    for sentence_key in page_sentence_keys
)

st.sidebar.markdown(f'**내 검수 기사 목록 <code style="color:#475569;">{filtered_article_count:,}</code>**', unsafe_allow_html=True)

if page_doc_ids:
    selection_key = filter_prefix + "_doc_" + hashlib.md5(f"{filter_key}|{offset}".encode("utf-8")).hexdigest()
    with st.sidebar:
        selected_id = render_article_selector(page_doc_ids, position, offset, selection_key)
    versions = versions_by_doc[selected_id]
    saved_versions = position.setdefault("versions", {})
    if len(versions) > 1:
        version_key = f"{selection_key}_version_{selected_id}"
        if st.session_state.get(version_key) not in versions:
            saved_version = saved_versions.get(selected_id)
            st.session_state[version_key] = saved_version if saved_version in versions else versions[0]
        selected_version = st.sidebar.selectbox("데이터 버전", versions, key=version_key)
    else:
        selected_version = versions[0]
    saved_versions[selected_id] = selected_version
    selected_doc_key = (selected_version, selected_id)
else:
    selected_doc_key = None
    st.info("현재 조회 조건에 맞는 기사가 없습니다.")

if selected_doc_key is not None:
    st.sidebar.button(
        "다음 기사", key=f"{filter_prefix}_next_article", type="tertiary",
        width="stretch", shortcut="Ctrl+Enter",
        help="현재 조회 조건의 다음 기사로 이동합니다. 수정 내용은 완료 버튼으로 저장한 뒤 이동하세요.",
        on_click=select_next_review_article,
        args=(
            (
                selected_press, press_versions[selected_press], selected_types, selected_review_method,
                authenticated_assignee, search_text, response_review_needed, response_review_status,
                completion_status,
            ),
            selected_entity, selected_id, position, filter_prefix, filter_key,
        ),
    )

#---------------------------------------------------------------------------------------------------------
# 사이드바 - 기사 목록 서식 및 페이지 이동
#---------------------------------------------------------------------------------------------------------
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
        on_click=lambda: position.update(offset=max(0, offset - PAGE_SIZE)),
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
            <span style="color:#94a3b8;">({f'{offset + 1:,}–{offset + len(page_doc_ids):,}' if page_doc_ids else '0'})</span>
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
        on_click=lambda: position.update(offset=offset + PAGE_SIZE),
    )

#---------------------------------------------------------------------------------------------------------
# 본문 - 선택한 기사에 포함된 문장 표시
#---------------------------------------------------------------------------------------------------------
def rule_result_html(rules):
    return "".join(
        '<div style="font-size:13px; padding:2px 0;">'
        f'<span style="color:#EF4444; font-weight:600;">{html.escape(RULE_NAMES.get(rule, rule))}</span>'
        ' 오류가 의심됩니다.</div>'
        for rule in sorted(set(rules))
    )


#---------------------------------------------------------------------------------------------------------
# 본문 구성 - 검수 사유 및 수정 제안 범위
#---------------------------------------------------------------------------------------------------------
def review_reason_text(response):
    messages = [
        RESPONSE_ERROR_MESSAGES[response[key]]
        for key in ("error_lv1", "error_lv2")
        if response.get(key) in RESPONSE_ERROR_MESSAGES
    ]
    reason = response.get("reason")
    if reason:
        messages.append(reason if reason.endswith((".", "!", "?")) else f"{reason}.")
    if messages:
        return " ".join(messages)
    if response.get("review_status") == "error":
        return "오류가 의심됩니다. 원문의 태깅을 확인해 주세요."
    return "검수 대상과 원문의 태깅을 비교해 주세요."


def proposal_source_range(form, position, corrected):
    """수정 제안이 주변 원문까지 포함하면 대응하는 유일한 원문 구간을 반환한다."""
    start, end = position
    target_text = ENTITY_PATTERN.sub(r"\1", form[start:end])
    proposed_text = ENTITY_PATTERN.sub(r"\1", corrected or "")
    if not target_text or target_text not in proposed_text or target_text == proposed_text:
        return position

    # 태그를 벗긴 원문의 경계를 원문 좌표로 되돌린다. 태그 내부에서 자르는 확장은 제외한다.
    offsets = [0]
    previous = 0
    for tag in ENTITY_PATTERN.finditer(form):
        offsets.extend(range(previous + 1, tag.start() + 1))
        offsets.extend([None] * (len(tag[1]) - 1))
        offsets.append(tag.end())
        previous = tag.end()
    offsets.extend(range(previous + 1, len(form) + 1))
    windows = []
    plain_form = ENTITY_PATTERN.sub(r"\1", form)
    for match in re.finditer(f"(?=({re.escape(proposed_text)}))", plain_form):
        left, right = (offsets[p] for p in match.span(1))
        if left is not None and right is not None and left <= start and end <= right:
            windows.append((left, right))
    return windows[0] if len(windows) == 1 else position


#---------------------------------------------------------------------------------------------------------
# 본문 구성 - 문장별 검수 참고 정보 생성
#---------------------------------------------------------------------------------------------------------
def build_review_references(item):
    """표시 내용이 같은 개체 행을 한 항목으로 묶고 각 행의 원문 위치를 보존한다."""
    form = item["original_form"] or ""
    responses = item.get("responses", [])
    entity_tags = {
        f"{item['sentence_id']}.E{i}": tag
        for i, tag in enumerate(ENTITY_PATTERN.finditer(form), 1)
    }
    # 전방 탐색으로 서로 겹치는 대상 표현의 시작 위치도 모두 찾는다.
    occurrences = {
        target: [m.span(1) for m in re.finditer(f"(?=({re.escape(target)}))", form)]
        for target in {row["target_span"] for row in responses if row.get("target_span")}
    }
    matches_by_entity = item["matches_by_entity"]
    fallback_matches = set()
    grouped = {}
    for row in responses:
        entity_id = row["entity_id"]
        target = row.get("target_span") or ""
        corrected = row.get("corrected_span")
        failed = row["validation_failed"]
        rules = ()
        reason = ""
        if failed:
            matches = matches_by_entity.get(entity_id, set()) | matches_by_entity.get(None, set())
            fallback_matches.update(matches)
            rules = tuple(sorted({rule for rule, _ in matches}))
        else:
            reason = review_reason_text(row)

        key = (target, corrected, failed, reason, rules)
        reference = grouped.setdefault(key, {
            "target_span": target, "corrected_span": corrected, "validation_failed": failed,
            "reason": reason, "rules": rules, "positions": set(),
        })
        positions = occurrences.get(target, ())
        if len(positions) > 1:
            tag = entity_tags.get(entity_id)
            positions = [
                (start, end) for start, end in positions
                if tag and start <= tag.start() and tag.end() <= end
            ]
        if len(positions) == 1:
            reference["positions"].add(proposal_source_range(form, positions[0], corrected))

    # 같은 위치에 서로 다른 제안이 있어도 조회 행 순서에 따라 번호가 바뀌지 않게 한다.
    references = sorted(grouped.values(), key=lambda ref: (
        min(ref["positions"], default=(len(form), len(form))),
        ref["target_span"], ref["corrected_span"] is None, ref["corrected_span"] or "",
        ref["validation_failed"], ref["reason"], ref["rules"],
    ))
    return references, fallback_matches


#---------------------------------------------------------------------------------------------------------
# 본문 구성 - 수정 제안 및 상세 사유 표시
#---------------------------------------------------------------------------------------------------------
def render_response_results(references, reference_key):
    entries = []
    for number, reference in enumerate(references, start=1):
        target = reference["target_span"] or "대상 표현 없음"
        corrected = reference["corrected_span"]
        suggestion = corrected or "삭제" if corrected is not None else "수정 제안 없음"
        summary = html.escape(f"{number}. {target} → {suggestion}")
        if reference["validation_failed"]:
            details_html = rule_result_html(reference["rules"]) or "룰 검출 결과 없음"
        else:
            details_html = html.escape(reference["reason"])

        open_attribute = " open" if number == 1 else ""
        entries.append(
            f'<details class="review-reference-entry" name="{reference_key}" '
            f'id="{reference_key}_{number}"{open_attribute}>'
            f'<summary title="{summary}">{summary}</summary>'
            f'<div class="review-reference-reason">{details_html}</div></details>'
        )
    if entries:
        st.markdown("".join(entries), unsafe_allow_html=True)


#---------------------------------------------------------------------------------------------------------
# 본문 구성 - 원문 및 수정문과 참고 정보 배치
#---------------------------------------------------------------------------------------------------------
def render_sentence_layout(idx, sentence_key, item, sentence_id, matches, decision_highlights):
    status_key = review_widget_key("review_status", sentence_key)
    modified_key = review_widget_key("modified_form", sentence_key)
    status = st.session_state.get(status_key, item.get("review_status") or "상태 없음")
    review_target = item.get("review_target") or "Y"
    # method_label = METHOD_DISPLAY_NAMES.get(item.get("review_method"), "참고 문장") if review_target == "Y" else "참고 문장"
    # if review_target == "Y" and item.get("review_method") == HUMAN_REVIEW_METHOD:
    #     method_label += " · 문장 " + (RESPONSE_STATUS_NAMES[item["sentence_result"]] if item.get("sentence_result") else "개체 판정 없음")
    # if item.get("rule_detected"):
    #     method_label += " · 룰 검출"
    references, fallback_matches = build_review_references(item)
    # 빈 문자열도 '삭제' 제안이므로 수정 제안에 포함한다.
    has_response_suggestion = any(
        ref["corrected_span"] is not None for ref in references
    )
    # 실패 항목에 표시한 룰은 공통 목록에서 중복 표시하지 않는다.
    show_rule_patterns = selected_review_method == BATCH_REVIEW_METHOD
    visible_rule_matches = [] if has_response_suggestion and not show_rule_patterns else [
        match for match in matches if match not in fallback_matches
    ]

    edit_key = review_widget_key("review_edit", sentence_key)
    reference_key = review_widget_key("review_references", sentence_key)
    selection_styles = []
    for number in range(1, len(references) + 1):
        scope = f'[data-testid="stHorizontalBlock"]:has(#{reference_key}_{number}[open]) .st-key-{edit_key}'
        selection_styles.extend((
            f'{scope} [data-review-target~="{number}"] {{border-block:2px solid #0F766E !important; border-inline:0 !important;}}',
            f'{scope} [data-review-start~="{number}"] {{border-inline-start:2px solid #0F766E !important;}}',
            f'{scope} [data-review-end~="{number}"] {{border-inline-end:2px solid #0F766E !important;}}',
        ))
    # 오른쪽 내용이 행 높이를 늘리지 않게 하고, 왼쪽 높이 안에서만 스크롤한다.
    st.html(f"""
        <style>
        .st-key-{reference_key} {{
            contain: size;
            min-height: 0 !important;
            overflow-y: auto;
            scrollbar-gutter: stable;
        }}
        .st-key-{reference_key} .review-reference-entry {{
            border-bottom: 1px solid #E2E8F0;
            font-size: 13px;
            line-height: 1.7;
        }}
        .st-key-{reference_key} summary {{
            display: block;
            padding: 8px 2px;
            cursor: pointer;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            list-style: none;
        }}
        .st-key-{reference_key} summary::before {{content: "▸ ";}}
        .st-key-{reference_key} details[open] > summary::before {{content: "▾ ";}}
        .st-key-{reference_key} details[open] > summary {{
            color: #0F766E;
            font-weight: 600;
        }}
        .st-key-{reference_key} summary:focus-visible {{
            outline: 2px solid #0F766E;
            outline-offset: -2px;
        }}
        .st-key-{reference_key} .review-reference-reason {{
            padding: 0 2px 10px;
            white-space: pre-wrap;
            overflow-wrap: anywhere;
        }}
        .st-key-{edit_key} .review-target-number {{
            color: #0F766E;
            font-weight: 700;
            margin-right: 2px;
        }}
        {"".join(selection_styles)}
        @media (max-width: 640px) {{
            .st-key-{reference_key} {{
                contain: none;
                max-height: 360px;
            }}
        }}
        </style>
    """)

    #---------------------------------------------------------------------------------------------------------
    # 문장 검수 - 상태 및 원문 표시
    #---------------------------------------------------------------------------------------------------------
    edit_col, rule_col = st.columns([3, 1])
    with edit_col:
        with st.container(border=True, height="content", key=edit_key):
            if status == "완료":
                completion_label = (
                    "재수정완료"
                    if st.session_state.get(
                        review_widget_key("revised", modified_key), False
                    )
                    else "수정완료"
                    if is_modified_form(
                        get_modified_form(sentence_key, item),
                        item.get("original_form") or "",
                    )
                    else "이상없음"
                )
                st.success(
                    f"문장 {idx:02d}: {sentence_id} · {completion_label}"
                )
            else:
                st.markdown(
                    f"`문장 {idx:02d}: {sentence_id}` "
                    f"`검수상태: {status}`"
                )
            # if selected_entity and any(
            #     (tag[1].strip(), tag[2].strip()) == selected_entity
            #     for tag in TAGGED_ENTITY_PATTERN.finditer(item["original_form"])
            # ):
            #     st.caption(f"우선 검수 개체 출현: {selected_entity[0]} · {selected_entity[1]}")
            st.markdown('<div style="margin-bottom:0.35rem; font-weight:600;">원문</div>', unsafe_allow_html=True)
            st.markdown(
                f"""<div style="min-height:100px; padding:0.75rem; border-radius:0.5rem; background-color:rgb(240, 242, 246); white-space:pre-wrap; word-break:break-word;">{highlighted_form_with_decision(item["original_form"], matches, decision_highlights, references, show_rule_patterns)}</div>""",
                unsafe_allow_html=True,
            )
            # if any(
            #     response.get("target_span")
            #     and response.get("corrected_span") is not None
            #     and response["corrected_span"] != response["target_span"]
            #     and response["target_span"] in item["original_form"]
            #     for response in item.get("responses", [])
            # ):
            #     st.caption("점선 테두리는 수정 제안이 있는 구간입니다. 마우스를 올리면 제안을 볼 수 있습니다.")
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
                    "재수정완료" if status == "완료" else "수정완료",
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
        with st.container(border=True, height="stretch", key=reference_key):
            # 검출 정보 
            st.markdown(
                """
                <div style="padding-top:10px; font-size:14px; font-weight:600;">
                    검수 참고 정보
                </div>
                """,
                unsafe_allow_html=True,
            ) 

            # if any(not ref["validation_failed"] for ref in references):
            #     st.caption("검수대상 → 수정제안 · 클릭시 상세 내용 확인 가능")

            if visible_rule_matches:
                st.markdown(
                    rule_result_html(rule for rule, _ in visible_rule_matches),
                    unsafe_allow_html=True,
                )
            decision = (
                filter_decision_types(item.get("decision", {}), selected_types)
                if show_detailed_review and (matches or references) else {}
            )
            if has_decision_result(decision):
                decision_results = []
                for label, key in (
                    ("태그 오류", "tagging_error_result"),
                    ("태깅 병합 오류", "tagging_merge_result"),
                ):
                    result = decision.get(key)
                    result_level = normalize_suspicion_level(result)
                    if result_level:
                        decision_results.append((result_level, label))

                for result_level, label in sorted(
                    decision_results,
                    key=lambda value: SUSPICION_PRIORITY[value[0]],
                    reverse=True,
                ):
                    st.markdown(
                        f'<div style="font-size:13px; padding:2px 0;">'
                        f'{html.escape(label)}가 의심됩니다. '
                        f'<span style="color:{SUSPICION_COLORS[result_level]}; font-weight:600;">'
                        f'의심도: {SUSPICION_LABELS[result_level]}</span></div>',
                        unsafe_allow_html=True,
                    )

            render_response_results(references, reference_key)
            if not visible_rule_matches and not has_decision_result(decision) and not references:
                st.caption("해당 없음")

#---------------------------------------------------------------------------------------------------------
# 본문 - 선택 기사 확인 및 표시 범위 설정
#---------------------------------------------------------------------------------------------------------
if selected_doc_key is None:
    st.info("좌측 사이드바에서 기사를 선택하면 검수 대상 문장이 표시됩니다.")

else:
    article_method = selected_review_method
    reference_status = "전체"
    if selected_review_method == HUMAN_REVIEW_METHOD:
        if grouped[docs[selected_doc_key][0]]["final_result"] == "error":
            reference_status = "error"
        else:
            # 최종 정상에는 다른 방식에 배정된 기사도 포함된다.
            article_method = None
    if st.session_state.get("full_article_doc_key") != selected_doc_key:
        st.session_state["full_article_doc_key"] = selected_doc_key
        st.session_state["show_full_article"] = False

    show_full_article = st.session_state.get("show_full_article", False)
    if st.button(
        "검수 대상만 보기" if show_full_article else "전체 기사보기",
        key="toggle_full_article_button",
        width="stretch",
        help="선택한 기사의 모든 문장을 표시합니다.",
    ):
        st.session_state["show_full_article"] = not show_full_article
        st.rerun()

    if show_full_article:
        full_article_rows = fetch_article_sentences(
            selected_doc_key[0],
            selected_doc_key[1],
            selected_press,
            authenticated_assignee,
            article_method,
            selected_types,
            response_review_needed,
            reference_status,
        )
        display_grouped = group_sentences(full_article_rows, selected_rules)
        selected_sentence_keys = sorted(
            display_grouped,
            key=sentence_sort_key,
        )
        st.caption(f"전체 기사 문장 {len(selected_sentence_keys):,}개")
    else:
        display_grouped = grouped
        selected_sentence_keys = docs[selected_doc_key]

    #---------------------------------------------------------------------------------------------------------
    # 본문 - 표시할 문장의 수정 상태 복원
    #---------------------------------------------------------------------------------------------------------
    for sentence_key in selected_sentence_keys:
        item = display_grouped[sentence_key]
        status_key = review_widget_key("review_status", sentence_key)
        modified_key = review_widget_key("modified_form", sentence_key)
        if status_key not in st.session_state:
            st.session_state[status_key] = item.get("review_status") or "미완료"
        value_key = review_value_key(sentence_key)
        if value_key not in st.session_state:
            st.session_state[value_key] = item.get("modified_form") or item.get("original_form") or ""
        st.session_state[modified_key] = st.session_state[value_key]

    selected_doc_id = selected_doc_key[1]

    try:
        response_results = fetch_response_results(
            selected_doc_key[0],
    #---------------------------------------------------------------------------------------------------------
    # 본문 - 검수 참고 정보 조회 및 연결
    #---------------------------------------------------------------------------------------------------------
            selected_press,
            selected_doc_id,
            response_review_needed,
            reference_status,
            selected_types,
        )
    except Exception as exc:
        st.error(f"검수 참고 정보 조회 실패: {exc}")
        st.stop()

    for sentence_key in selected_sentence_keys:
        item = display_grouped[sentence_key]
        item["responses"] = response_results.get(item["sentence_id"], [])

    if selected_review_method == BATCH_REVIEW_METHOD and not show_full_article:
        # 이미 조회한 현재 페이지의 배정 문장만 사용해 전체 데이터 적재와 숨은 변경을 피한다.
        batch_grouped = grouped
        batch_sentence_keys = list(batch_grouped)
    #---------------------------------------------------------------------------------------------------------
    # 일괄처리 - 현재 페이지 대상 및 저장 대기 문장 구성
    #---------------------------------------------------------------------------------------------------------
        pending_sentence_keys = [
            key for key in batch_sentence_keys
            if st.session_state.get(review_widget_key("batch_pending", key)) == filter_key
        ]

        batch_processing_message = st.session_state.pop("batch_processing_message", None)
        if batch_processing_message:
            st.success(batch_processing_message)
        
        st.caption(
            f"일괄처리 범위: 현재 페이지 {len(page_doc_ids):,}기사. "
            + (f"선택한 {selected_entity[0]} · {selected_entity[1]} 중 하이라이트된 태그만 변환합니다. " if selected_entity
            else "하이라이트된 태그만 변환합니다. ")
            + f"현재 조건에서 일괄처리하거나 완료로 표시한 {len(pending_sentence_keys):,}문장만 일괄저장합니다."
        )
        action_layout_col, _ = st.columns([3, 1])
        with action_layout_col:
            with st.container():
                batch_col, save_col = st.columns(2, gap="small")
                with batch_col:
                    st.button(
                        "일괄처리",
                        key="batch_processing_button",
                        width="stretch",
                        help="현재 페이지에서 선택한 개체 조건에 맞고 하이라이트된 <X: Y>를 X 형태로 변환합니다.",
                        on_click=apply_batch_processing,
                        args=(batch_sentence_keys, batch_grouped, selected_entity),
                    )
                with save_col:
                    if st.button(
                        "일괄저장",
                        key="batch_save_review_button",
                        disabled=not pending_sentence_keys,
                        width="stretch",
                        help="현재 조건과 페이지에서 일괄처리하거나 완료로 표시한 문장만 저장합니다.",
                    ):
                        review_updates = []
                        for sentence_key in pending_sentence_keys:
                            item = batch_grouped[sentence_key]
                            modified_form = get_modified_form(sentence_key, item)
                            status_key = review_widget_key("review_status", sentence_key)
                            if (
                                not is_modified_form(modified_form, item.get("original_form"))
                                and st.session_state.get(status_key) != "완료"
                            ):
                                continue
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
                        for sentence_key in pending_sentence_keys:
                            st.session_state.pop(review_widget_key("batch_pending", sentence_key), None)
                        st.session_state["batch_processing_message"] = (
                            "일괄처리 결과를 저장했습니다."
                        )
                        st.rerun()

    #---------------------------------------------------------------------------------------------------------
    # 본문 - 문장별 검수 영역 표시
    #---------------------------------------------------------------------------------------------------------
    for idx, sentence_key in enumerate(selected_sentence_keys, start=1):
        item = display_grouped[sentence_key]
        sentence_id = item["sentence_id"]
        matches = sorted(
            item["matches"],
            key=lambda value: (value[0], value[1])
        )
        decision_highlights = (
            get_decision_highlights(filter_decision_types(item.get("decision", {}), selected_types))
            if show_detailed_review and (matches or item.get("responses")) else []
        )

        with st.container():
            render_sentence_layout(
                idx,
                sentence_key,
                item,
                sentence_id,
                matches,
                decision_highlights,
            )
            continue
