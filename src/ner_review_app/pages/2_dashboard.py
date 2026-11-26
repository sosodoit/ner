# -*- coding: utf-8 -*-
"""언론사별 휴먼 검수 현황 화면"""
import sys
import os
import pandas as pd
import streamlit as st
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.postgredb import get_postgre_connect
from src.ner_review_app.modules.review_targets import HUMAN_REVIEW_METHOD, METHOD_DISPLAY_NAMES, REVIEW_SCOPE_CTES

METHOD_ORDER = ["일괄처리", "LLM검수", "휴먼검수"]
ASSIGNMENT_PASSWORD_ENV = "NER_ASSIGNMENT_PASSWORD"


def _fetch_dataframe(cursor, query, params=None):
    cursor.execute(query, params)
    rows = cursor.fetchall()
    columns = [column.name for column in cursor.description]
    return pd.DataFrame(rows, columns=columns)


@st.cache_data(ttl=3600, show_spinner=False)
def load_original_counts():
    with get_postgre_connect() as connection, connection.cursor() as cursor:
        return _fetch_dataframe(cursor, """
            SELECT publisher AS press, COUNT(DISTINCT doc_id) AS original_count
            FROM public.ner_documents GROUP BY publisher
        """)


def load_review_data():
    method_query = f"""
        WITH {REVIEW_SCOPE_CTES}, method_articles AS (
            SELECT s.press, s.doc_id, s.review_method, a.article_result,
                   BOOL_AND(s.review_status = '완료') FILTER (
                       WHERE s.review_method <> 'LLM검수' OR s.sentence_result = 'error'
                   ) AS completed,
                   COUNT(DISTINCT s.sentence_id) FILTER (WHERE s.sentence_result = 'error') AS error_sentences
            FROM review_sentences s
            LEFT JOIN human_articles a ON a.press = s.press AND a.doc_id = s.doc_id
                                      AND s.review_method = 'LLM검수'
            GROUP BY s.press, s.doc_id, s.review_method, a.article_result
        ), rule_counts AS (
            SELECT press, COUNT(DISTINCT doc_id) FILTER (WHERE rule_detected) AS rule_count
            FROM review_sentences GROUP BY press
        )
        SELECT press, review_method, rule_count, COUNT(*) AS assigned_count,
               COUNT(*) FILTER (WHERE article_result = 'error') AS error_count,
               COUNT(*) FILTER (WHERE article_result = 'normal') AS normal_count,
               COUNT(*) FILTER (WHERE completed IS NOT NULL) AS target_count,
               COUNT(*) FILTER (WHERE completed) AS completed_count,
               SUM(error_sentences)::bigint AS error_sentences
        FROM method_articles JOIN rule_counts USING (press)
        GROUP BY press, review_method, rule_count ORDER BY press, review_method
    """
    # 원천 개체 오류에서 출발하는 역방향 집계로 대상 누락, 중복, 부분 완료 오집계를 확인한다.
    check_query = """
        WITH judged AS (
            SELECT h.press, h.doc_id, BOOL_OR(v.review_status = 'error') AS has_error,
                   BOOL_AND(h.review_status = '완료') FILTER (WHERE v.review_status = 'error') AS completed,
                   COUNT(DISTINCT h.sentence_id) FILTER (WHERE v.review_status = 'error') AS error_sentences
            FROM public.ner_reviews v JOIN public.ner_runs run USING (run_id)
            JOIN public.ner_human_review h
              ON h.data_version = run.data_version AND h.press = SPLIT_PART(v.run_id, '_', 7)
             AND h.doc_id = v.doc_id AND h.sentence_id = v.sentence_id
            WHERE v.entity_id IS NOT NULL AND v.review_status IN ('error', 'normal') AND h.review_method = %s
            GROUP BY h.press, h.doc_id
        )
        SELECT press, COUNT(*) FILTER (WHERE has_error) AS error_count,
               COUNT(*) FILTER (WHERE NOT has_error) AS normal_count,
               COUNT(*) FILTER (WHERE completed) AS completed_count, SUM(error_sentences) AS error_sentences
        FROM judged GROUP BY press
    """
    assignment_query = """
        SELECT
            COALESCE(press, '미상') AS press,
            COALESCE(NULLIF(BTRIM(assignee), ''), '미배정') AS assignee,
            review_method,
            COUNT(DISTINCT (data_version, doc_id))::BIGINT AS article_count
        FROM ner_human_review
        GROUP BY
            COALESCE(press, '미상'),
            COALESCE(NULLIF(BTRIM(assignee), ''), '미배정'),
            review_method
        ORDER BY press, assignee, review_method
    """

    with get_postgre_connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            methods = _fetch_dataframe(cursor, method_query, (None, None, None))
            expected = _fetch_dataframe(cursor, check_query, (HUMAN_REVIEW_METHOD,))
            assignments = _fetch_dataframe(cursor, assignment_query)

    human = methods[methods["review_method"] == HUMAN_REVIEW_METHOD].set_index("press")
    expected = expected.set_index("press").sort_index()
    actual = human.loc[human["error_count"] + human["normal_count"] > 0, expected.columns]
    if not actual.sort_index().astype("int64").equals(expected.astype("int64")):
        raise ValueError("언론사별 오류·정상·완료 기사 수 또는 오류 문장 수가 원천 판정과 다릅니다.")

    summary = load_original_counts().set_index("press")
    summary = summary.join(methods.groupby("press")["rule_count"].max(), how="outer")
    for method, column in (("일괄처리", "batch_count"), ("휴먼검수", "martial_count")):
        counts = methods.loc[methods["review_method"] == method].set_index("press")["assigned_count"]
        summary[column] = counts
    summary = summary.join(human[["assigned_count", "error_count", "normal_count", "completed_count"]])
    summary = summary.fillna(0).astype("int64")
    summary["judged_count"] = summary["normal_count"] + summary["error_count"]
    summary["pending_count"] = summary["assigned_count"] - summary["judged_count"]
    summary["incomplete_count"] = summary["error_count"] - summary["completed_count"]
    return {"summary": summary.sort_index().reset_index(), "methods": methods, "assignments": assignments}


def assign_articles(press, review_method, assignee, article_count, password):
    expected_password = os.getenv(ASSIGNMENT_PASSWORD_ENV, "")
    if not expected_password or password != expected_password:
        return False, "비밀번호가 올바르지 않거나 서버에 배정 비밀번호가 설정되지 않았습니다."

    target_query = """
        SELECT data_version, press, doc_id, review_method
        FROM ner_human_review
        WHERE press = %s
          AND review_method = %s
        GROUP BY data_version, press, doc_id, review_method
        ORDER BY data_version, doc_id
        LIMIT %s
    """
    update_query = """
        WITH target_articles AS (
            SELECT data_version, press, doc_id, review_method
            FROM ner_human_review
            WHERE press = %s
              AND review_method = %s
            GROUP BY data_version, press, doc_id, review_method
            ORDER BY data_version, doc_id
            LIMIT %s
        )
        UPDATE ner_human_review AS h
        SET assignee = %s
        FROM target_articles AS t
        WHERE h.data_version = t.data_version
          AND h.press = t.press
          AND h.doc_id = t.doc_id
          AND h.review_method = t.review_method
    """

    with get_postgre_connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(target_query, (press, review_method, article_count))
            assigned_count = len(cursor.fetchall())
            if assigned_count == 0:
                return True, "배정할 기사가 없습니다."
            cursor.execute(update_query, (press, review_method, article_count, assignee))

    return True, f"{assigned_count:,}건의 기사를 {assignee} 담당으로 배정/재배정했습니다."


def render_review_statistics(data):
    summary = data["summary"]
    methods = data["methods"]

    with st.container(border=True):
        title_col, refresh_col = st.columns([10, 0.5], vertical_alignment="center")
        title_col.markdown("**NER 검수 현황**")
        refresh_col.button("", icon=":material/refresh:", help="최신 검수 현황 조회", type="tertiary")
        st.caption("원본은 언론사별 고유 기사 수입니다.")
        st.caption("최종 휴먼검수는 `계엄기사`, LLM검출건 중 `오류` 기사입니다.")
        st.caption("개체 오류가 하나라도 있으면 오류 문장입니다. 오류 문장이 있는 기사는 오류로, 정상 판정만 있는 기사는 정상으로 한 번 셉니다. "
                   "오류 문장을 모두 완료하면 해당 기사의 휴먼검수가 완료됩니다.")

    tab1, tab2, tab3 = st.tabs(["언론사별 검수 현황", "언론사별 검수 방식", "담당자 배정"])
    with tab1:
        count_labels = {
            "original_count": "원본기사", "martial_count": "계엄기사", "batch_count": "일괄처리",
            "rule_count": "룰검출", "judged_count": "LLM검출", "error_count": "오류", 
            "completed_count": "검수 완료", "incomplete_count": "검수 미완료",
        }
        totals = summary[list(count_labels)].sum().to_dict()
        display = pd.concat([pd.DataFrame([{"press": "전체 합계", **totals}]), summary], ignore_index=True)
        display["완료율"] = (display["completed_count"].div(display["error_count"].replace(0, float("nan"))).fillna(0).mul(100).round(1))
        display = display[["press", *count_labels, "완료율"]].rename(columns={"press": "언론사", **count_labels})
        st.dataframe(display, width="stretch", hide_index=True, height=(len(display) + 1) * 35 + 3,
                     column_config={"완료율": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f%%")})

    with tab2:
        for row in summary.itertuples(index=False):
            with st.expander(f"{row.press} · 원본 {row.original_count:,}기사 · 최종 휴먼검수 {row.error_count:,}기사"):
                values = methods.loc[methods["press"] == row.press].set_index("review_method")
                values = values.reindex(METHOD_ORDER, fill_value=0)[["assigned_count", "target_count", "completed_count"]]
                values["미완료 기사"] = values["target_count"] - values["completed_count"]
                values["완료율"] = values["completed_count"].div(values["target_count"].replace(0, float("nan"))).fillna(0).mul(100)
                values.index = values.index.map(METHOD_DISPLAY_NAMES).rename("검수 방식")
                st.dataframe(values.reset_index().rename(columns={
                    "assigned_count": "분류 기사", "target_count": "실제 검수 대상", "completed_count": "완료 기사",
                }), width="stretch", hide_index=True, column_config={
                    "완료율": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f%%")
                })
                st.caption(f"휴먼검수 분류 {row.assigned_count:,}기사 중 판정 있음 {row.judged_count:,}기사 "
                           f"(오류 {row.error_count:,} · 정상 {row.normal_count:,}), 판정 없음 {row.pending_count:,}기사")

    with tab3:
        #---------------------------------------------------------------------------------------------------------
        # 본문 - 담당자 배정
        #---------------------------------------------------------------------------------------------------------
        with st.container(border=True):
            st.markdown("**배정 현황**")
            st.caption("배정 기사 수는 검수 방식별 기사ID 순차적으로 배정됩니다.")

            assignments = data["assignments"].copy()
            grouping_columns = ["press", "review_method"]
            assigned = assignments[assignments["assignee"] != "미배정"]
            assigned_display = (
                assigned.groupby(grouping_columns + ["assignee"], as_index=False)["article_count"]
                .sum()
            )
            all_method_rows = assignments[grouping_columns].drop_duplicates()
            assigned_method_rows = assigned_display[grouping_columns].drop_duplicates()
            missing_method_rows = all_method_rows.merge(
                assigned_method_rows,
                on=grouping_columns,
                how="left",
                indicator=True,
            )
            missing_method_rows = missing_method_rows[
                missing_method_rows["_merge"] == "left_only"
            ][grouping_columns]
            if not missing_method_rows.empty:
                missing_method_rows = missing_method_rows.assign(
                    assignee="미배정",
                    article_count=0,
                )
                assigned_display = pd.concat(
                    [assigned_display, missing_method_rows],
                    ignore_index=True,
                )

            unassigned_counts = (
                assignments[assignments["assignee"] == "미배정"]
                .groupby(grouping_columns, as_index=False)["article_count"]
                .sum()
                .rename(columns={"article_count": "unassigned_article_count"})
            )
            assignment_display = assigned_display.merge(
                unassigned_counts,
                on=grouping_columns,
                how="left",
            )
            assignment_display["unassigned_article_count"] = (
                assignment_display["unassigned_article_count"].fillna(0).astype(int)
            )
            assignment_display = assignment_display.rename(
                columns={
                    "press": "언론사",
                    "review_method": "검수방식",
                    "assignee": "담당자",
                    "article_count": "배정 기사 수",
                    "unassigned_article_count": "미배정 기사 수",
                }
            )
            assignment_display["검수방식"] = assignment_display["검수방식"].map(
                lambda method: METHOD_DISPLAY_NAMES.get(method, method)
            )
            assignment_display = assignment_display[
                [
                    "언론사",
                    "검수방식",
                    "담당자",
                    "배정 기사 수",
                    "미배정 기사 수",
                ]
            ]
            st.dataframe(assignment_display, width="stretch", hide_index=True)

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
                assign_col1, assign_col2, assign_col3, assign_col4 = st.columns(4)
                with assign_col1:
                    selected_assignment_press = st.selectbox("언론사", press_options)
                with assign_col2:
                    selected_assignment_method = st.selectbox(
                        "검수방식",
                        METHOD_ORDER,
                        format_func=lambda method: METHOD_DISPLAY_NAMES.get(method, method),
                    )
                with assign_col3:
                    selected_assignee = st.text_input(
                        "담당자",
                        value=existing_assignees[0] if existing_assignees else "",
                    )
                with assign_col4:
                    assignment_count = st.number_input(
                        "배정 기사 수",
                        min_value=1,
                        value=1,
                        step=1,
                    )

                assignment_password = st.text_input("배정 비밀번호", type="password")
                if st.button("기사 배정", type="primary"):
                    if not selected_assignee.strip():
                        st.error("담당자를 입력해 주세요.")
                    else:
                        success, message = assign_articles(
                            selected_assignment_press,
                            selected_assignment_method,
                            selected_assignee.strip(),
                            int(assignment_count),
                            assignment_password,
                        )
                        if success:
                            st.cache_data.clear()
                            st.success(message)
                            st.rerun()
                        else:
                            st.error(message)


try:
    with st.spinner("검수 현황을 조회하는 중입니다..."):
        review_data = load_review_data()
except Exception as exc:
    st.error(f"검수 현황을 불러오지 못했습니다: {exc}")
else:
    render_review_statistics(review_data)
