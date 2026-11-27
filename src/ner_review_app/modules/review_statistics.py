# -*- coding: utf-8 -*-
"""검수 현황 조회와 캐시. 검수 저장 후에는 현황 캐시만 갱신한다."""
#---------------------------------------------------------------------------------------------------------
# 기본 설정 - 라이브러리 및 검수 집계 모듈
#---------------------------------------------------------------------------------------------------------
import pandas as pd
import streamlit as st
from src.config.postgredb import get_postgre_connect
from src.ner_review_app.modules.review_targets import HUMAN_REVIEW_METHOD, REVIEW_SCOPE_CTES


#---------------------------------------------------------------------------------------------------------
# 기능 - 쿼리 결과의 데이터프레임 변환
#---------------------------------------------------------------------------------------------------------
def _fetch_dataframe(cursor, query, params=None):
    cursor.execute(query, params)
    rows = cursor.fetchall()
    columns = [column.name for column in cursor.description]
    return pd.DataFrame(rows, columns=columns)


#---------------------------------------------------------------------------------------------------------
# 데이터 조회 - 언론사별 원본 기사 수
#---------------------------------------------------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def load_original_counts():
    with get_postgre_connect() as connection, connection.cursor() as cursor:
        return _fetch_dataframe(cursor, """
            SELECT publisher AS press, COUNT(DISTINCT doc_id) AS original_count
            FROM public.ner_documents GROUP BY publisher
        """)


#---------------------------------------------------------------------------------------------------------
# 데이터 조회 - 검수 현황 및 담당자 배정 집계
#---------------------------------------------------------------------------------------------------------
@st.cache_data(ttl=900, show_spinner=False)
def load_review_data():
    #---------------------------------------------------------------------------------------------------------
    # 집계 쿼리 - 검수방식별 대상 및 완료 기사
    #---------------------------------------------------------------------------------------------------------
    method_query = f"""
        WITH {REVIEW_SCOPE_CTES}, method_articles AS (
            SELECT s.press, s.doc_id, s.review_method,
                   BOOL_AND(s.review_status = '완료') FILTER (
                       WHERE s.review_method <> 'LLM검수' OR (r.final_result = 'error' AND s.human_error)
                   ) AS completed,
                   COUNT(*) FILTER (WHERE r.final_result = 'error' AND s.human_error) AS error_sentences
            FROM review_sentences s
            LEFT JOIN rule_articles r USING (press, doc_id)
            GROUP BY s.press, s.doc_id, s.review_method
        ), rule_counts AS (
            SELECT press, COUNT(*) AS rule_count,
                   COUNT(*) FILTER (WHERE final_result = 'error') AS rule_error_count,
                   COUNT(*) FILTER (WHERE final_result = 'normal') AS rule_normal_count
            FROM rule_articles GROUP BY press
        )
        SELECT press, review_method, rule_count, rule_error_count, rule_normal_count, COUNT(*) AS assigned_count,
               COUNT(*) FILTER (WHERE completed IS NOT NULL) AS target_count,
               COUNT(*) FILTER (WHERE completed) AS completed_count,
               SUM(error_sentences)::bigint AS error_sentences
        FROM method_articles LEFT JOIN rule_counts USING (press)
        GROUP BY press, review_method, rule_count, rule_error_count, rule_normal_count ORDER BY press, review_method
    """
    #---------------------------------------------------------------------------------------------------------
    # 집계 쿼리 - 원천 판정 기준 교차 확인
    #---------------------------------------------------------------------------------------------------------
    # 원천 개체 오류에서 출발하는 역방향 집계로 대상 누락, 중복, 부분 완료 오집계를 확인한다.
    check_query = """
        WITH evidence AS (
            SELECT DISTINCT h.press, h.doc_id, TRUE AS detected,
                   NULL::boolean AS completed, 0 AS error_sentences
            FROM public.ner_human_review h
            JOIN public.ner_rule_results_3 r USING (data_version, doc_id, sentence_id)
            UNION ALL
            SELECT h.press, h.doc_id, FALSE, BOOL_AND(h.review_status = '완료'),
                   COUNT(DISTINCT (h.data_version, h.sentence_id))
            FROM public.ner_reviews v JOIN public.ner_runs run USING (run_id)
            JOIN public.ner_human_review h
              ON h.data_version = run.data_version AND h.press = SPLIT_PART(v.run_id, '_', 7)
             AND h.doc_id = v.doc_id AND h.sentence_id = v.sentence_id
            WHERE v.entity_id IS NOT NULL AND v.review_status = 'error' AND h.review_method = %s
            GROUP BY h.press, h.doc_id
        ), checked_articles AS (
            SELECT press, doc_id, BOOL_OR(completed) AS completed, SUM(error_sentences) AS error_sentences
            FROM evidence GROUP BY press, doc_id HAVING BOOL_OR(detected)
        )
        SELECT press, COUNT(completed) AS target_count,
               COUNT(*) FILTER (WHERE completed IS NULL) AS rule_normal_count,
               COUNT(*) FILTER (WHERE completed) AS completed_count, SUM(error_sentences) AS error_sentences
        FROM checked_articles GROUP BY press
    """
    #---------------------------------------------------------------------------------------------------------
    # 집계 쿼리 - 언론사 및 담당자별 배정 기사
    #---------------------------------------------------------------------------------------------------------
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

    #---------------------------------------------------------------------------------------------------------
    # 집계 쿼리 - 전체검수대상 밖 원본 기사의 후처리 현황
    #---------------------------------------------------------------------------------------------------------
    sample_query = f"""
        WITH {REVIEW_SCOPE_CTES}, original_articles AS (
            SELECT DISTINCT publisher AS press, doc_id FROM public.ner_documents
        ), target_articles AS (
            SELECT DISTINCT s.press, s.doc_id
            FROM review_sentences s
            LEFT JOIN rule_articles r USING (press, doc_id)
            WHERE s.review_method <> 'LLM검수'
               OR (r.final_result = 'error' AND s.human_error)
        ), postprocessed_articles AS (
            SELECT press, doc_id,
                   BOOL_AND(review_status IS NOT DISTINCT FROM '완료') AS completed
            FROM public.ner_human_review_add
            GROUP BY press, doc_id
        )
        SELECT o.press, COUNT(*) AS original_count,
               COUNT(t.doc_id) AS target_count,
               COUNT(*) FILTER (WHERE t.doc_id IS NULL) AS normal_count,
               COUNT(*) FILTER (
                   WHERE t.doc_id IS NULL AND a.completed
               ) AS postprocessed_count,
               COUNT(*) FILTER (
                   WHERE t.doc_id IS NULL AND NOT COALESCE(a.completed, FALSE)
               ) AS true_normal_count
        FROM original_articles o
        LEFT JOIN target_articles t USING (press, doc_id)
        LEFT JOIN postprocessed_articles a USING (press, doc_id)
        GROUP BY o.press ORDER BY o.press
    """

    #---------------------------------------------------------------------------------------------------------
    # 데이터 조회 - 동일 시점의 검수 현황 및 배정 결과
    #---------------------------------------------------------------------------------------------------------
    with get_postgre_connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            methods = _fetch_dataframe(cursor, method_query, (None, None, None))
            expected = _fetch_dataframe(cursor, check_query, (HUMAN_REVIEW_METHOD,))
            assignments = _fetch_dataframe(cursor, assignment_query)
            sample_summary = _fetch_dataframe(cursor, sample_query, (None, None, None))

    #---------------------------------------------------------------------------------------------------------
    # 집계 확인 - 원천 판정과 현황 집계의 일치 여부
    #---------------------------------------------------------------------------------------------------------
    human = methods[methods["review_method"] == HUMAN_REVIEW_METHOD].set_index("press")
    rules = methods.groupby("press")[["rule_count", "rule_error_count", "rule_normal_count"]].max()
    expected = expected.set_index("press").sort_index()
    actual = rules.loc[rules["rule_count"] > 0, ["rule_normal_count"]].join(
        human[["target_count", "completed_count", "error_sentences"]]
    ).fillna(0)[expected.columns]
    if not actual.sort_index().astype("int64").equals(expected.astype("int64")):
        raise ValueError("언론사별 오류·정상·완료 기사 수 또는 오류 문장 수가 원천 판정과 다릅니다.")

    #---------------------------------------------------------------------------------------------------------
    # 집계 구성 - 언론사별 원본 및 검수 진행 현황
    #---------------------------------------------------------------------------------------------------------
    summary = load_original_counts().set_index("press")
    summary = summary.join(rules, how="outer")
    for method, column in (("일괄처리", "batch_count"), ("휴먼검수", "martial_count")):
        counts = methods.loc[methods["review_method"] == method].set_index("press")["assigned_count"]
        summary[column] = counts
    progress = methods.groupby("press")[["target_count", "completed_count"]].sum()
    summary = summary.join(progress)
    summary = summary.fillna(0).astype("int64")
    summary["incomplete_count"] = summary["target_count"] - summary["completed_count"]
    return {
        "summary": summary.sort_index().reset_index(), "methods": methods,
        "assignments": assignments, "sample_summary": sample_summary,
    }


#---------------------------------------------------------------------------------------------------------
# 기능 - 검수 현황 조회 캐시 초기화
#---------------------------------------------------------------------------------------------------------
def refresh_dashboard():
    load_original_counts.clear()
    load_review_data.clear()
