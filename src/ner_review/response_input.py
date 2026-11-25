# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: Response 기사 입력 조회
# * 작성일: 2026-11-24
# * 설명: 선택한 기사의 전체 문장과 Decision 재검토 근거 구성
# ***************************************************
import re
from itertools import groupby
from operator import itemgetter

from psycopg.rows import dict_row

from src.config import get_postgre_connect

ENTITY_PATTERN = re.compile(r"<([^<>:]+):\s*(PS|LC|OG|AF|DT|EV)>")

ARTICLE_SQL = """
    SELECT n.doc_id, n.paragraph_id, n.sentence_id, n.form, n.document_title,
           n.author, n.date, n.topic, n.original_topic, d.review_candidate,
           d.detected_entities, d.candidate_rule_ids, evidence.rule_evidence,
           d.tagging_error_probability, d.tagging_error_result, d.tagging_error_confidence,
           d.tagging_merge_probability, d.tagging_merge_result, d.tagging_merge_confidence
    FROM public.ner_documents n
    LEFT JOIN public.ner_decision_results d
      ON d.data_version = %(version)s AND d.press = %(press)s
     AND d.doc_id = n.doc_id AND d.sentence_id = n.sentence_id
    LEFT JOIN LATERAL (
        SELECT jsonb_agg(jsonb_build_object('rule_id', rule_id, 'pattern', rule ->> 'pattern')
                         ORDER BY rule_id) AS rule_evidence
        FROM public.ner_rule_results rr
        CROSS JOIN LATERAL jsonb_each(rr.rule_results) AS item(rule_id, rule)
        WHERE rr.data_version = %(version)s AND rr.doc_id = n.doc_id
          AND rr.sentence_id = n.sentence_id AND (rule ->> 'detected')::boolean IS TRUE
    ) evidence ON d.review_candidate IS TRUE
    WHERE n.doc_id = ANY(%(ids)s)
    ORDER BY n.doc_id, n.paragraph_order, n.paragraph_id, n.sentence_order, n.sentence_id
"""


def _sentence(row):
    sentence_id = row["sentence_id"]
    form = row["form"]
    decision = None
    entities = []
    if row["review_candidate"] is True:
        decision = {key: row[key] for key in (
            "review_candidate", "detected_entities",
            "tagging_error_probability", "tagging_error_result", "tagging_error_confidence",
            "tagging_merge_probability", "tagging_merge_result", "tagging_merge_confidence",
        )}
        rule_ids = (row["candidate_rule_ids"] or "").split(",")
        decision["candidate_rule_ids"] = [value.strip() for value in rule_ids if value.strip()]
        entities = [
            {"entity_id": f"{sentence_id}.E{i}", "target_span": match[0],
             "target_type": match[2], "rule_evidence": []}
            for i, match in enumerate(ENTITY_PATTERN.finditer(form), 1)
        ]
    return {"id": sentence_id, "form": form, "decision": decision, "entities": entities,
            "sentence_rule_evidence": row["rule_evidence"] or []}


def load_response_documents(doc_ids, *, data_version, press):
    """한 배치의 ID만 조회한다. API 실행 전에 DB 연결을 반환한다."""
    with get_postgre_connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(ARTICLE_SQL, {"ids": list(doc_ids), "version": data_version, "press": press})
        rows = cursor.fetchall()
    documents = []
    for doc_id, article in groupby(rows, itemgetter("doc_id")):
        article = list(article)
        first = article[0]
        paragraphs = [
            {"id": paragraph_id, "sentence": [_sentence(row) for row in paragraph]}
            for paragraph_id, paragraph in groupby(article, itemgetter("paragraph_id"))
        ]
        metadata = {field: first[field] for field in ("author", "date", "topic", "original_topic")}
        metadata.update(title=first["document_title"], publisher=press)
        documents.append({"id": doc_id, "metadata": metadata, "paragraph": paragraphs})
    return documents
