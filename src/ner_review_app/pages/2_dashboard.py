# -*- coding: utf-8 -*-
"""언론사별 휴먼 검수 현황 화면"""
#---------------------------------------------------------------------------------------------------------
# 기본 설정 - 라이브러리 불러오기
#---------------------------------------------------------------------------------------------------------
import sys
import os
import pandas as pd
import streamlit as st
from pathlib import Path

#---------------------------------------------------------------------------------------------------------
# 기본 설정 - 프로젝트 경로 및 모듈 불러오기
#---------------------------------------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.postgredb import get_postgre_connect
from src.ner_review_app.modules.review_rows import load_review_rows
from src.ner_review_app.modules.review_targets import METHOD_DISPLAY_NAMES
from src.ner_review_app.modules.review_statistics import load_review_data, refresh_dashboard


#---------------------------------------------------------------------------------------------------------
# 기본 설정 - 검수 방식 및 환경 변수
#---------------------------------------------------------------------------------------------------------
METHOD_ORDER = ["일괄처리", "휴먼검수", "LLM검수"]
ASSIGNMENT_PASSWORD_ENV = "NER_ASSIGNMENT_PASSWORD"
ASSIGNMENT_ERROR_TYPES = {
    "tagging_error": "태그 오류", "tagging_wrong": "오태깅", "tagging_miss": "태깅 누락",
    "span_error": "범위 오류", "etc": "기타",
}


def assignment_target_query(press, review_methods, completion_status, error_types):
    query = """
        WITH assignment_articles AS (
            SELECT h.data_version, h.press, h.doc_id, h.review_method,
                   BOOL_AND(h.review_status IS NOT DISTINCT FROM '완료') AS completed,
                   BOOL_OR(%s OR EXISTS (
                       SELECT 1 FROM public.ner_reviews v
                       JOIN public.ner_runs run USING (run_id)
                       WHERE run.data_version = h.data_version
                         AND SPLIT_PART(v.run_id, '_', 7) = h.press
                         AND v.doc_id = h.doc_id AND v.sentence_id = h.sentence_id
                         AND v.review_status = 'error'
                         AND COALESCE(NULLIF(BTRIM(v.error_lv1), ''), 'etc') = ANY(%s)
                   ) OR EXISTS (
                       SELECT 1 FROM public.ner_rule_results_3 r
                       CROSS JOIN LATERAL jsonb_each(to_jsonb(r)) AS rule(key, value)
                       WHERE r.data_version = h.data_version AND r.doc_id = h.doc_id
                         AND r.sentence_id = h.sentence_id AND rule.value = 'true'::jsonb
                         AND CASE
                             WHEN rule.key LIKE 'EXT_E003_%%' THEN 'tagging_wrong'
                             WHEN rule.key = 'EXT_S003'
                               OR rule.key LIKE 'EXT_E004_%%'
                               OR rule.key LIKE 'EXT_E005_%%'
                               OR rule.key LIKE 'EXT_E006_%%' THEN 'span_error'
                         END = ANY(%s)
                         AND NOT EXISTS (
                             SELECT 1 FROM public.ner_reviews v
                             JOIN public.ner_runs run USING (run_id)
                             WHERE run.data_version = r.data_version
                               AND SPLIT_PART(v.run_id, '_', 7) = h.press
                               AND v.doc_id = r.doc_id AND v.sentence_id = r.sentence_id
                               AND (v.entity_id = r.entity_id OR r.entity_id IS NULL)
                               AND v.review_status IN ('error', 'normal')
                               AND STRPOS(COALESCE(v.reason, ''), '[자동검증 실패]') = 0
                         )
                   )) AS matches_error
            FROM public.ner_human_review h
            WHERE h.press = %s AND h.review_method = ANY(%s)
            GROUP BY h.data_version, h.press, h.doc_id, h.review_method
        )
        SELECT data_version, press, doc_id, review_method FROM assignment_articles
        WHERE matches_error AND (%s OR completed = %s)
    """
    params = (
        set(error_types) == set(ASSIGNMENT_ERROR_TYPES), list(error_types), list(error_types),
        press, list(review_methods), completion_status == "전체", completion_status == "완료",
    )
    return query, params


#---------------------------------------------------------------------------------------------------------
# 기능 - 기사 담당자 배정
#---------------------------------------------------------------------------------------------------------
def assign_articles(press, review_methods, assignee, article_count, password, completion_status, error_types):
    expected_password = os.getenv(ASSIGNMENT_PASSWORD_ENV, "")
    if not expected_password or password != expected_password:
        return False, "비밀번호가 올바르지 않거나 서버에 배정 비밀번호가 설정되지 않았습니다."

    target_query, params = assignment_target_query(press, review_methods, completion_status, error_types)
    update_query = f"""
        WITH target_articles AS (
            {target_query}
            ORDER BY data_version, doc_id, review_method
            LIMIT %s
        )
        UPDATE ner_human_review AS h
        SET assignee = %s
        FROM target_articles AS t
        WHERE h.data_version = t.data_version
          AND h.press = t.press
          AND h.doc_id = t.doc_id
          AND h.review_method = t.review_method
        RETURNING h.data_version, h.press, h.doc_id, h.review_method
    """

    with get_postgre_connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(update_query, (*params, article_count, assignee))
            assigned_count = len(set(cursor.fetchall()))
            if assigned_count == 0:
                return True, "배정할 기사가 없습니다."

    return True, f"{assigned_count:,}건의 기사를 {assignee} 담당으로 배정/재배정했습니다."


#---------------------------------------------------------------------------------------------------------
# 화면 - 검수 현황 렌더링
#---------------------------------------------------------------------------------------------------------
def render_review_statistics(data):
    summary = data["summary"]
    methods = data["methods"]

    #---------------------------------------------------------------------------------------------------------
    # 상단 - 검수 현황 안내 및 새로고침
    #---------------------------------------------------------------------------------------------------------
    with st.container(border=True):
        title_col, refresh_col = st.columns([10, 0.5], vertical_alignment="center")
        title_col.markdown("**NER 검수 현황**")
        refresh_col.button("", icon=":material/refresh:", help="검수 현황 재조회", type="tertiary", on_click=refresh_dashboard)
        st.caption("우측 새로고침 아이콘을 누르면 **최신 데이터로 다시 조회**합니다.")
        st.caption("집계 단위는 고유 기사 건수입니다.")
        st.caption("**전체검수대상**은 `계엄기사·일괄처리·휴먼검수` 최종 오류 기사 수의 합계이며, 완료율 계산의 기준입니다.")
        st.caption("문장에 개체 오류가 하나라도 있으면 오류로 판정합니다.")

    #---------------------------------------------------------------------------------------------------------
    # 본문 - 탭 구성
    #---------------------------------------------------------------------------------------------------------
    tab1, tab2, sample_tab, tab3 = st.tabs([
        "언론사별 검수 현황", "언론사별 검수 방식", "샘플 검수 현황", "담당자 배정",
    ])
    with tab1:
        #---------------------------------------------------------------------------------------------------------
        # 본문 - 언론사별 검수 현황
        #---------------------------------------------------------------------------------------------------------
        count_labels = {
            "original_count": "원본기사", "batch_count": "일괄처리", "martial_count": "계엄기사", "rule_error_count": "휴먼검수",
            "target_count": "전체검수대상", "completed_count": "전체검수완료", "incomplete_count": "전체검수미완료",
        }
        totals = summary[list(count_labels)].sum().to_dict()
        display = pd.concat([pd.DataFrame([{"press": "전체합계", **totals}]), summary], ignore_index=True)
        display["완료율"] = (display["completed_count"].div(display["target_count"].replace(0, float("nan"))).fillna(0).mul(100).round(1))
        display = display[["press", *count_labels, "완료율"]].rename(columns={"press": "언론사", **count_labels})
        header_background = (
            st.get_option("theme.dataframeHeaderBackgroundColor")
            or st.get_option("theme.secondaryBackgroundColor")
            or ("#262730" if st.get_option("theme.base") == "dark" else "#f0f2f6")
        )
        styled_display = display.style.set_properties(
            subset=(display.index[display["언론사"] == "전체합계"], slice(None)),
            **{"background-color": header_background, "font-weight": "bold"},
        )
        for column, color in {
            "전체검수대상": "#2563eb",
            "전체검수완료": "#15803d",
            "전체검수미완료": "#c2410c",
        }.items():
            styled_display = styled_display.set_properties(subset=[column], **{"color": color})
        st.dataframe(styled_display, width="stretch", hide_index=True, height=(len(display) + 1) * 35 + 3,
                     column_config={"완료율": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f%%")})

    with tab2:
        #---------------------------------------------------------------------------------------------------------
        # 본문 - 언론사별 검수 방식
        #---------------------------------------------------------------------------------------------------------
        for row in summary.itertuples(index=False):
            values = methods.loc[methods["press"] == row.press].set_index("review_method")
            values = values.reindex(METHOD_ORDER, fill_value=0)[["assigned_count", "target_count", "completed_count"]]
            llm_target_count = int(values.loc["LLM검수", "assigned_count"])
            values["룰검출대상"] = values["assigned_count"]
            values.loc["LLM검수", "룰검출대상"] = row.rule_count
            values["LLM검수대상"] = 0
            values.loc["LLM검수", "LLM검수대상"] = llm_target_count
            target_ratio = row.target_count / row.original_count * 100 if row.original_count else 0
            
            with st.expander(f"{row.press} · 원본 {row.original_count:,}기사 · 전체검수대상 {row.target_count:,}기사 ({target_ratio:.1f}%)"):
                values["미완료 기사"] = values["target_count"] - values["completed_count"]
                values["완료율"] = values["completed_count"].div(values["target_count"].replace(0, float("nan"))).fillna(0).mul(100)
                values.index = values.index.map(METHOD_DISPLAY_NAMES).rename("검수방식")
                method_display = values[[
                    "룰검출대상", "LLM검수대상", "target_count", "completed_count", "미완료 기사", "완료율",
                ]].reset_index().rename(columns={
                    "target_count": "최종검수대상", "completed_count": "완료기사",
                })
                styled_methods = method_display.style.set_properties(
                    subset=["최종검수대상"], **{"color": "#2563eb"},
                ).set_properties(
                    subset=["완료기사"], **{"color": "#15803d"},
                ).set_properties(
                    subset=["미완료 기사"], **{"color": "#c2410c"},
                )
                st.dataframe(styled_methods, width="stretch", hide_index=True, column_config={
                    "완료율": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f%%")
                })

    with sample_tab:
        #---------------------------------------------------------------------------------------------------------
        # 본문 - 언론사별 샘플 검수 및 후처리 현황
        #---------------------------------------------------------------------------------------------------------
        st.caption("**정상건**은 원본기사 중 전체검수대상이 아닌 기사입니다. 검수방식이 겹쳐도 기사는 한 번만 집계합니다.")
        st.caption("**찐정상건**은 정상건에서 후처리완료건을 뺀 나머지입니다.")
        sample_labels = {
            "original_count": "원본기사", "normal_count": "정상건",
            "postprocessed_count": "후처리완료건", "true_normal_count": "찐정상건",
        }
        sample_summary = data["sample_summary"]
        sample_totals = sample_summary[list(sample_labels)].sum().to_dict()
        sample_display = pd.concat([
            pd.DataFrame([{"press": "전체합계", **sample_totals}]), sample_summary,
        ], ignore_index=True)
        sample_display = sample_display[["press", *sample_labels]].rename(
            columns={"press": "언론사", **sample_labels},
        )
        styled_sample = sample_display.style.set_properties(
            subset=(sample_display.index[sample_display["언론사"] == "전체합계"], slice(None)),
            **{"background-color": header_background, "font-weight": "bold"},
        ).set_properties(
            subset=["후처리완료건"], **{"color": "#15803d"},
        ).set_properties(
            subset=["찐정상건"], **{"color": "#2563eb"},
        )
        st.dataframe(
            styled_sample, width="stretch", hide_index=True, height=(len(sample_display) + 1) * 35 + 3,
        )

    with tab3:
        st.session_state.pop("assignment_count_filter", None)
        render_assignment_panel(data)


#---------------------------------------------------------------------------------------------------------
# 화면 - 담당자 배정 독립 갱신
#---------------------------------------------------------------------------------------------------------
@st.fragment
def render_assignment_panel(data):
    result_message = st.session_state.pop("assignment_result_message", None)
    if result_message:
        st.success(result_message)
    #---------------------------------------------------------------------------------------------------------
    # 본문 - 담당자 배정
    #---------------------------------------------------------------------------------------------------------
    with st.container(border=True):
        st.markdown("**배정 현황**")
        st.caption("미배정 건수는 미배정 행에 표시됩니다. 선택 조건에 맞는 기사를 기사ID 순서로 배정/재배정합니다.")

        #---------------------------------------------------------------------------------------------------------
        # 담당자 배정 - 배정 현황 집계
        #---------------------------------------------------------------------------------------------------------
        assignments = data["assignments"].copy()
        assignment_display = assignments.pivot_table(
            index=["press", "assignee"], columns="review_method",
            values="article_count", aggfunc="sum", fill_value=0,
        ).reindex(columns=METHOD_ORDER, fill_value=0).astype(int)
        assignment_display.columns = [METHOD_DISPLAY_NAMES[method] for method in METHOD_ORDER]
        assignment_display = assignment_display.reset_index().rename(
            columns={"press": "언론사", "assignee": "담당자"},
        )
        st.dataframe(assignment_display, width="stretch", hide_index=True)

        #---------------------------------------------------------------------------------------------------------
        # 담당자 배정 - 기사 배정 및 재배정 입력
        #---------------------------------------------------------------------------------------------------------
        st.divider()
        st.markdown("**기사 배정/재배정**")

        press_options = sorted(assignments["press"].dropna().unique().tolist())
        press_options = [press for press in press_options if press != "미상"]
        existing_assignees = sorted(
            assignee
            for assignee in assignments["assignee"].dropna().unique()
            if assignee != "미배정"
        )

        if not press_options:
            st.info("배정 가능한 언론사가 없습니다.")
        else:
            assign_col1, assign_col2, assign_col3 = st.columns(3)
            with assign_col1:
                selected_assignment_press = st.selectbox("언론사", press_options)
            with assign_col2:
                selected_assignment_methods = st.multiselect(
                    "검수방식",
                    METHOD_ORDER,
                    default=METHOD_ORDER,
                    format_func=lambda method: METHOD_DISPLAY_NAMES.get(method, method),
                )
            with assign_col3:
                selected_assignee = st.text_input(
                    "담당자",
                    value=existing_assignees[0] if existing_assignees else "",
                )
            status_col, error_col = st.columns([1, 2])
            with status_col:
                assignment_status = st.selectbox("검수 상태", ["전체", "미완료", "완료"])
            with error_col:
                assignment_error_types = st.multiselect(
                    "오류 유형", list(ASSIGNMENT_ERROR_TYPES),
                    default=list(ASSIGNMENT_ERROR_TYPES),
                    format_func=ASSIGNMENT_ERROR_TYPES.get,
                )
            count_filter = (
                selected_assignment_press, tuple(sorted(selected_assignment_methods)),
                assignment_status, tuple(sorted(assignment_error_types)),
            )
            if st.session_state.get("assignment_count_filter") != count_filter:
                target_query, target_params = assignment_target_query(
                    selected_assignment_press, selected_assignment_methods,
                    assignment_status, assignment_error_types,
                )
                with get_postgre_connect() as connection, connection.cursor() as cursor:
                    cursor.execute(f"SELECT COUNT(*) FROM ({target_query}) AS targets", target_params)
                    st.session_state["assignment_max_article_count"] = int(cursor.fetchone()[0])
                st.session_state["assignment_count_filter"] = count_filter
            max_article_count = st.session_state["assignment_max_article_count"]
            assignment_filter = (*count_filter, max_article_count)
            if st.session_state.get("assignment_filter") != assignment_filter:
                st.session_state["assignment_article_count"] = max_article_count
                st.session_state["assignment_filter"] = assignment_filter
            assignment_count = st.number_input(
                "배정 기사 수", min_value=1 if max_article_count else 0,
                max_value=max_article_count, value=max_article_count, step=1,
                key="assignment_article_count", disabled=max_article_count == 0,
                help="선택 조건에 맞는 최대 기사 수가 자동 입력됩니다. 여러 검수방식에서 합산한 건수입니다.",
            )
            st.caption(f"배정 가능한 최대 기사 수: {max_article_count:,}건 · 기존 담당자가 있는 기사도 재배정에 포함됩니다.")

            #---------------------------------------------------------------------------------------------------------
            # 담당자 배정 - 비밀번호 확인 및 배정 실행
            #---------------------------------------------------------------------------------------------------------
            assignment_password = st.text_input("배정 비밀번호", type="password")
            if st.button("기사 배정", type="primary", disabled=max_article_count == 0):
                if not selected_assignee.strip():
                    st.error("담당자를 입력해 주세요.")
                else:
                    success, message = assign_articles(
                        selected_assignment_press,
                        selected_assignment_methods,
                        selected_assignee.strip(),
                        int(assignment_count),
                        assignment_password,
                        assignment_status,
                        assignment_error_types,
                    )
                    if success:
                        load_review_data.clear()
                        load_review_rows.clear()
                        st.session_state["assignment_result_message"] = message
                        st.rerun()
                    else:
                        st.error(message)


#---------------------------------------------------------------------------------------------------------
# 실행 - 검수 데이터 조회 및 화면 표시
#---------------------------------------------------------------------------------------------------------
try:
    with st.spinner("검수 현황을 조회하는 중입니다..."):
        review_data = load_review_data()
except Exception as exc:
    st.error(f"검수 현황을 불러오지 못했습니다: {exc}")
else:
    render_review_statistics(review_data)
