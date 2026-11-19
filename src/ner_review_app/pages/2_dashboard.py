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

METHOD_ORDER = ["일괄처리", "LLM검수", "휴먼검수"]
METHOD_DISPLAY_NAMES = {"일괄처리": "일괄처리", "LLM검수": "휴먼검수", "휴먼검수": "계엄기사"}
ASSIGNMENT_PASSWORD_ENV = "NER_ASSIGNMENT_PASSWORD"


def _fetch_dataframe(cursor, query):
    cursor.execute(query)
    rows = cursor.fetchall()
    columns = [column.name for column in cursor.description]
    return pd.DataFrame(rows, columns=columns)


@st.cache_data(ttl=3600, show_spinner=False)
def load_review_data():
    """ner_human_review의 집계와 기사 목록을 캐시 가능한 형태로 조회한다."""
    summary_query = """
        SELECT
            COALESCE(press, '미상') AS press,
            COUNT(DISTINCT doc_id)::BIGINT AS article_count,
            COUNT(*)::BIGINT AS sentence_count,
            COUNT(*) FILTER (WHERE review_status = '완료')::BIGINT AS completed_sentence_count,
            COUNT(*) FILTER (WHERE review_status = '미완료')::BIGINT AS incomplete_sentence_count,
            COUNT(*) FILTER (WHERE is_modified = TRUE)::BIGINT AS modified_sentence_count
        FROM ner_human_review
        GROUP BY COALESCE(press, '미상')
        ORDER BY press
    """
    article_query = """
        SELECT
            COALESCE(press, '미상') AS press,
            doc_id,
            COUNT(*)::BIGINT AS sentence_count,
            COUNT(*) FILTER (WHERE review_status = '완료')::BIGINT AS completed_sentence_count,
            COUNT(*) FILTER (WHERE review_status = '미완료')::BIGINT AS incomplete_sentence_count,
            COUNT(*) FILTER (WHERE is_modified = TRUE)::BIGINT AS modified_sentence_count
        FROM ner_human_review
        GROUP BY COALESCE(press, '미상'), doc_id
        ORDER BY press, doc_id
    """
    method_query = """
        SELECT
            COALESCE(press, '미상') AS press,
            review_method,
            COUNT(*)::BIGINT AS sentence_count,
            COUNT(*) FILTER (WHERE review_status = '완료')::BIGINT AS completed_sentence_count,
            COUNT(*) FILTER (WHERE review_status = '미완료')::BIGINT AS incomplete_sentence_count
        FROM ner_human_review
        GROUP BY COALESCE(press, '미상'), review_method
        ORDER BY press, review_method
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
            summary = _fetch_dataframe(cursor, summary_query)
            articles = _fetch_dataframe(cursor, article_query)
            method_summary = _fetch_dataframe(cursor, method_query)
            assignments = _fetch_dataframe(cursor, assignment_query)

    return {
        "summary": summary,
        "articles": articles,
        "method_summary": method_summary,
        "assignments": assignments,
    }


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


def _prepare_summary(summary):
    """집계 결과에 화면 표시용 진행률을 추가한다."""
    if summary.empty:
        return summary

    result = summary.copy()
    result["progress"] = (
        result["completed_sentence_count"]
        .div(result["sentence_count"].where(result["sentence_count"] != 0))
        .fillna(0)
        .mul(100)
        .round(1)
    )
    return result


def _prepare_method_summary(method_summary, press=None):
    """검수 방식별 집계를 준비하고, 데이터가 없는 방식은 0건으로 표시한다."""
    if press is not None:
        method_summary = method_summary[method_summary["press"] == press]

    grouped = (
        method_summary.groupby("review_method", as_index=False)[
            ["sentence_count", "completed_sentence_count", "incomplete_sentence_count"]
        ]
        .sum()
    )
    result = pd.DataFrame({"review_method": METHOD_ORDER}).merge(
        grouped, on="review_method", how="left"
    )
    count_columns = [
        "sentence_count",
        "completed_sentence_count",
        "incomplete_sentence_count",
    ]
    result[count_columns] = result[count_columns].fillna(0).astype(int)
    return _prepare_summary(result)


def render_review_statistics(data):
    """캐시된 검수 현황을 화면에 표시한다."""
    summary = _prepare_summary(data["summary"])
    articles = data["articles"]
    method_summary = data["method_summary"]

    #---------------------------------------------------------------------------------------------------------
    # 상단 - 화면 정보
    #---------------------------------------------------------------------------------------------------------
    with st.container(border=True):
        title_col, refresh_col = st.columns([10, 0.5], vertical_alignment="center")

        with title_col:
            st.markdown("**NER 검수 데이터 관리**")

        with refresh_col:
            if st.button("", icon=":material/refresh:", help="최신 데이터로 새로고침", type="tertiary"):
                st.cache_data.clear()
                st.rerun()

        st.caption("※ :material/refresh: 클릭시 최신 데이터로 갱신됩니다. (기준테이블: `ner_human_review`)")

    if summary.empty:
        st.info("표시할 검수 데이터가 없습니다.")
        return

    tab1, tab2, tab3 = st.tabs(["언론사별 검수 현황", "언론사별 기사 목록", "담당자 배정"])
    with tab1:
        #---------------------------------------------------------------------------------------------------------
        # 본문 - 언론사별 검수 현황 
        #---------------------------------------------------------------------------------------------------------
        total_articles = int(articles[["press", "doc_id"]].drop_duplicates().shape[0])
        total_sentences = int(summary["sentence_count"].sum())
        total_completed = int(summary["completed_sentence_count"].sum())
        total_incomplete = int(summary["incomplete_sentence_count"].sum())
        total_modified = int(summary["modified_sentence_count"].sum())
        total_progress = (total_completed / total_sentences * 100) if total_sentences else 0
        
        # 검수방법별 집계
        method_counts = method_summary.pivot_table(
            index="press",
            columns="review_method",
            values="sentence_count",
            aggfunc="sum",
            fill_value=0,
        )
        summary = summary.copy()
        for method in METHOD_ORDER:
            summary[f"{method}_sentence_count"] = (
                summary["press"].map(method_counts[method] if method in method_counts else {})
                .fillna(0)
                .astype(int)
            )

        with st.container(border=True):
            st.markdown("**언론사별 검수 현황**")

            # 언론사별 상세 테이블
            display_summary = summary[
                [
                    "press",
                    "article_count",
                    "sentence_count",
                    "completed_sentence_count",
                    "incomplete_sentence_count",
                    "modified_sentence_count",
                    "일괄처리_sentence_count",
                    "LLM검수_sentence_count",
                    "휴먼검수_sentence_count",
                    "progress",
                ]
            ].rename(
                columns={
                    "press": "언론사",
                    "article_count": "전체 기사",
                    "sentence_count": "전체 문장",
                    "completed_sentence_count": "완료 문장",
                    "incomplete_sentence_count": "미완료 문장",
                    "modified_sentence_count": "수정 문장",
                    "일괄처리_sentence_count": f"{METHOD_DISPLAY_NAMES['일괄처리']} 문장",
                    "LLM검수_sentence_count": f"{METHOD_DISPLAY_NAMES['LLM검수']} 문장",
                    "휴먼검수_sentence_count": f"{METHOD_DISPLAY_NAMES['휴먼검수']} 문장",
                    "progress": "진행률",
                }
            )

            # 전체 합계 행 추가
            total_row = {
                "언론사": "전체 합계",
                "전체 기사": total_articles,
                "전체 문장": total_sentences,
                "완료 문장": total_completed,
                "미완료 문장": total_incomplete,
                "수정 문장": total_modified,
                f"{METHOD_DISPLAY_NAMES['일괄처리']} 문장": summary["일괄처리_sentence_count"].sum(),
                f"{METHOD_DISPLAY_NAMES['LLM검수']} 문장": summary["LLM검수_sentence_count"].sum(),
                f"{METHOD_DISPLAY_NAMES['휴먼검수']} 문장": summary["휴먼검수_sentence_count"].sum(),
                "진행률": total_progress,
            }
            
            summary = summary.sort_values("press").reset_index(drop=True)
            display_summary = pd.concat(
                [pd.DataFrame([total_row]), display_summary],
                ignore_index=True,
            )

            # 상세 테이블 컬럼 스타일
            styled_summary = display_summary.style

            # 전체 합계 행
            styled_summary = styled_summary.set_properties(
                subset=pd.IndexSlice[0, :],
                **{
                    "background-color": "#F0F4F8",
                    "font-weight": "bold",
                },
            )
            # 검수방법별 컬럼 색상
            method_colors = {
                f"{METHOD_DISPLAY_NAMES['일괄처리']} 문장": "#EAF2FF",  # 파랑
                f"{METHOD_DISPLAY_NAMES['LLM검수']} 문장": "#EAF6EC",  # 초록
                f"{METHOD_DISPLAY_NAMES['휴먼검수']} 문장": "#F3EDFF",  # 보라
            }
            for column, color in method_colors.items():
                if column in display_summary.columns:
                    styled_summary = styled_summary.set_properties(subset=[column], **{"background-color": color})
            st.dataframe(
                styled_summary,
                width="stretch",
                hide_index=True,
                height=(len(display_summary) + 1) * 35 + 3,
                column_config={
                    "진행률": st.column_config.ProgressColumn(
                        "진행률",
                        min_value=0,
                        max_value=100,
                        format="%.1f%%",
                    )
                },
            )

    with tab2:
        #---------------------------------------------------------------------------------------------------------
        # 본문 - 언론사별 기사 목록
        #---------------------------------------------------------------------------------------------------------
        with st.container(border=True):
            
            st.markdown("**언론사별 기사 목록**")

            for press in summary["press"]:
                press_summary = summary.loc[summary["press"] == press].iloc[0]
                press_articles = articles[articles["press"] == press].copy()
                progress = float(press_summary["progress"])

                with st.expander(f"{press} · 기사 {int(press_summary['article_count']):,}건 · 진행률 {progress:.1f}%"):
                    st.markdown("**검수 방식별 진행률**")
                    press_method_display = _prepare_method_summary(method_summary, press)[
                        [
                            "review_method",
                            "sentence_count",
                            "completed_sentence_count",
                            "incomplete_sentence_count",
                            "progress",
                        ]
                    ].rename(
                        columns={
                            "review_method": "검수 방식",
                            "sentence_count": "전체 문장",
                            "completed_sentence_count": "완료 문장",
                            "incomplete_sentence_count": "미완료 문장",
                            "progress": "진행률",
                        }
                    )
                    press_method_display["검수 방식"] = press_method_display["검수 방식"].map(METHOD_DISPLAY_NAMES)
                    
                    # 검수 방식별 셀 배경색
                    method_bg_colors = {
                        METHOD_DISPLAY_NAMES["일괄처리"]: "#EAF2FF",
                        METHOD_DISPLAY_NAMES["LLM검수"]: "#EAF6EC",
                        METHOD_DISPLAY_NAMES["휴먼검수"]: "#F3EDFF",
                    }

                    press_method_display = press_method_display.style.map(
                        lambda value: f"background-color: {method_bg_colors.get(value, 'transparent')}",
                        subset=["검수 방식"],
                    )

                    st.dataframe(
                        press_method_display,
                        width="stretch",
                        hide_index=True,
                        column_config={"진행률": st.column_config.ProgressColumn("진행률", min_value=0, max_value=100, format="%.1f%%")}
                    )

                    st.markdown("**기사 목록**")
                    
                    # 문서 ID 마지막 숫자 기준 오름차순 정렬
                    article_display = press_articles.copy()
                    article_display["_sort"] = (article_display["doc_id"].str.split(".").str[-1].astype(int))
                    article_display = article_display.sort_values("_sort")

                    article_display = article_display[
                        [
                            "doc_id",
                            "sentence_count",
                            "completed_sentence_count",
                            "incomplete_sentence_count",
                            "modified_sentence_count",
                        ]
                    ].rename(
                        columns={
                            "doc_id": "문서 ID",
                            "sentence_count": "전체 문장",
                            "completed_sentence_count": "완료 문장",
                            "incomplete_sentence_count": "미완료 문장",
                            "modified_sentence_count": "수정 문장",
                        }
                    )

                    st.dataframe(article_display, width="stretch", hide_index=True)

    with tab3:
        #---------------------------------------------------------------------------------------------------------
        # 본문 - 담당자 배정
        #---------------------------------------------------------------------------------------------------------
        with st.container(border=True):
            st.markdown("**배정 현황**")

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
