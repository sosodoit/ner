"""검수 화면과 현황에서 사용하는 배정 문장, 개체 판정, 기사 판정."""

HUMAN_REVIEW_METHOD = "LLM검수"
METHOD_DISPLAY_NAMES = {"일괄처리": "일괄처리", HUMAN_REVIEW_METHOD: "휴먼검수", "휴먼검수": "계엄기사"}

# 파라미터는 언론사, 데이터 버전 목록, 기사 ID 순서이며 NULL은 전체 범위다.
REVIEW_SCOPE_CTES = """
    scope AS NOT MATERIALIZED (
        SELECT %s::text AS press, %s::text[] AS versions, %s::text AS doc_id
    ), entity_verdicts AS (
        SELECT run.data_version, SPLIT_PART(v.run_id, '_', 7) AS press, v.doc_id, v.sentence_id,
               CASE WHEN BOOL_OR(v.review_status = 'error') THEN 'error' ELSE 'normal' END AS sentence_result
        FROM public.ner_reviews v JOIN public.ner_runs run USING (run_id) CROSS JOIN scope p
        WHERE v.entity_id IS NOT NULL AND v.review_status IN ('error', 'normal')
          AND (p.press IS NULL OR SPLIT_PART(v.run_id, '_', 7) = p.press)
          AND (p.versions IS NULL OR run.data_version = ANY(p.versions))
          AND (p.doc_id IS NULL OR v.doc_id = p.doc_id)
        GROUP BY 1, 2, 3, 4
    ), rule_keys AS (
        SELECT DISTINCT r.data_version, r.doc_id, r.sentence_id
        FROM public.ner_rule_results_3 r CROSS JOIN scope p
        WHERE (p.versions IS NULL OR r.data_version = ANY(p.versions))
          AND (p.doc_id IS NULL OR r.doc_id = p.doc_id)
    ), review_sentences AS (
        SELECT h.data_version, h.press, h.doc_id, h.sentence_id, h.review_method,
               h.review_status, h.assignee, v.sentence_result, r.doc_id IS NOT NULL AS rule_detected,
               h.review_method = 'LLM검수' AND v.sentence_result = 'error' AS human_error
        FROM public.ner_human_review h
        LEFT JOIN entity_verdicts v USING (data_version, doc_id, sentence_id, press)
        LEFT JOIN rule_keys r USING (data_version, doc_id, sentence_id)
        CROSS JOIN scope p
        WHERE (p.press IS NULL OR h.press = p.press)
          AND (p.versions IS NULL OR h.data_version = ANY(p.versions))
          AND (p.doc_id IS NULL OR h.doc_id = p.doc_id)
    ), human_articles AS (
        SELECT press, doc_id,
               CASE WHEN BOOL_OR(sentence_result = 'error') THEN 'error'
                    WHEN BOOL_OR(sentence_result = 'normal') THEN 'normal' END AS article_result
        FROM review_sentences WHERE review_method = 'LLM검수'
        GROUP BY press, doc_id
    ), rule_articles AS (
        SELECT press, doc_id,
               CASE WHEN BOOL_OR(human_error) THEN 'error' ELSE 'normal' END AS final_result
        FROM review_sentences
        GROUP BY press, doc_id
        HAVING BOOL_OR(rule_detected)
    )
"""
