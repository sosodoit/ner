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
from src.ner_review_app.modules.review_targets import METHOD_DISPLAY_NAMES
from src.ner_review_app.modules.review_statistics import load_review_data, refresh_dashboard
from src.ner_review_app.modules.review_rows import load_review_rows

METHOD_ORDER = ["일괄처리", "LLM검수", "휴먼검수"]
ASSIGNMENT_PASSWORD_ENV = "NER_ASSIGNMENT_PASSWORD"


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
        refresh_col.button("", icon=":material/refresh:", help="원본·검수 현황 다시 조회",
                           type="tertiary", on_click=refresh_dashboard)
        st.caption("검수 현황은 최대 15분간 재사용합니다. 새로고침을 누르면 현재 DB에서 다시 조회합니다.")
        st.caption("원본은 언론사별 고유 기사 수입니다.")
        st.caption("최종 휴먼검수는 계엄기사·일괄처리·휴먼검수 최종 오류 기사 수의 합계이며, 완료율 계산의 기준입니다.")
        st.caption("룰 검출 기사 중 휴먼검수 대상 문장에 개체 오류가 하나라도 있으면 최종 오류, 나머지는 최종 정상입니다. "
                   "개체 판정이 없는 기사도 최종 정상에 포함합니다. 직접 검수는 대상 오류 문장을 모두 완료하면 완료로 셉니다.")

    tab1, tab2, tab3 = st.tabs(["언론사별 검수 현황", "언론사별 검수 방식", "담당자 배정"])
    with tab1:
        st.caption("완료율은 계엄기사·일괄처리·최종 오류의 완료 기사 수를 세 방식의 검수 대상 기사 수로 나눈 값입니다.")
        count_labels = {
            "original_count": "원본기사", "martial_count": "계엄기사", "batch_count": "일괄처리",
            "rule_count": "룰 검출 전체", "rule_error_count": "최종 오류", "rule_normal_count": "최종 정상",
            "target_count": "검수 대상", "completed_count": "검수 완료", "incomplete_count": "검수 미완료",
        }
        totals = summary[list(count_labels)].sum().to_dict()
        display = pd.concat([pd.DataFrame([{"press": "전체 합계", **totals}]), summary], ignore_index=True)
        display["완료율"] = (display["completed_count"].div(display["target_count"].replace(0, float("nan"))).fillna(0).mul(100).round(1))
        display = display[["press", *count_labels, "완료율"]].rename(columns={"press": "언론사", **count_labels})
        st.dataframe(display, width="stretch", hide_index=True, height=(len(display) + 1) * 35 + 3,
                     column_config={"완료율": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f%%")})

    with tab2:
        for row in summary.itertuples(index=False):
            values = methods.loc[methods["press"] == row.press].set_index("review_method")
            values = values.reindex(METHOD_ORDER, fill_value=0)[["assigned_count", "target_count", "completed_count"]]
            with st.expander(f"{row.press} · 원본 {row.original_count:,}기사 · 최종 휴먼검수 {row.target_count:,}기사"):
                values["미완료 기사"] = values["target_count"] - values["completed_count"]
                values["완료율"] = values["completed_count"].div(values["target_count"].replace(0, float("nan"))).fillna(0).mul(100)
                values.index = values.index.map(METHOD_DISPLAY_NAMES).rename("검수 방식")
                st.dataframe(values.reset_index().rename(columns={
                    "assigned_count": "분류 기사(배정)", "target_count": "검수 대상", "completed_count": "완료 기사",
                }), width="stretch", hide_index=True, column_config={
                    "완료율": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f%%")
                })
                st.caption(f"휴먼검수 판정 전체(룰 검출) {row.rule_count:,}기사 · 최종 오류 {row.rule_error_count:,}기사 · 최종 정상 {row.rule_normal_count:,}기사")

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
                            load_review_data.clear()
                            load_review_rows.clear()
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
