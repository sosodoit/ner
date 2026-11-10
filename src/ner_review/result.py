# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER 검수 결과 처리
# * 작성일: 2026-11-08
# * 설명: LLM 검수 결과 정규화 및 JSONL 결과, 메타데이터 저장
# ***************************************************
import json

def safe_error_message(error):
    return f"{type(error).__name__}: request failed"

def normalize_reviews(results, sentences):
    # LLM 결과를 원문 순서에 맞춰 재정렬
    reviews_by_sentence_id = {}
    entities_by_key = {
        (sentence["sentence_id"], entity.get("entity_id")): entity
        for sentence in sentences
        for entity in sentence.get("entities", [])
    }
    for review in results:
        sentence_id = review.get("sentence_id")
        reviews_by_sentence_id.setdefault(sentence_id, []).append(review)

    normalized_results = []
    for sentence in sentences:
        sentence_id = sentence["sentence_id"]
        sentence_reviews = reviews_by_sentence_id.get(sentence_id, [])
        entities = sentence.get("entities", [])

        # LLM 호출은 성공했지만 결과가 누락된 경우
        if not sentence_reviews:
            fallback_entities = entities or [{"entity_id": None}]
            for entity in fallback_entities:
                normalized_results.append({
                    "sentence_id": sentence["sentence_id"],
                    "entity_id": entity.get("entity_id"),
                    "target_type": entity.get("target_type"),
                    "llm_review_status": "unreviewed",
                    "review_status": "error",
                    "target_span": None,
                    "corrected_span": None,
                    "error_lv1": None,
                    "error_lv2": None,
                    "reason": None,
                    "review_needed": True,
                })
            continue

        # 결과를 반환한 각 검수 행을 reviewed로 표시
        for review in sentence_reviews:
            normalized_review = dict(review)
            entity = entities_by_key.get(
                (sentence_id, normalized_review.get("entity_id")),
                {},
            )
            normalized_review["target_type"] = entity.get("target_type")
            normalized_review["llm_review_status"] = "reviewed"
            normalized_results.append(normalized_review)

        reviewed_entity_ids = {
            review.get("entity_id")
            for review in sentence_reviews
        }
        for entity in entities:
            entity_id = entity.get("entity_id")
            if entity_id in reviewed_entity_ids:
                continue

            normalized_results.append({
                "sentence_id": sentence["sentence_id"],
                "entity_id": entity_id,
                "target_type": entity.get("target_type"),
                "llm_review_status": "unreviewed",
                "review_status": "error",
                "target_span": None,
                "corrected_span": None,
                "error_lv1": None,
                "error_lv2": None,
                "reason": None,
                "review_needed": True,
            })

    return normalized_results

def normalize_sentences(results, sentences):
    # 수정 문장을 원문 순서에 맞춰 재정렬
    corrected_by_sentence_id = {
        item["sentence_id"]: item["corrected_sentence"]
        for item in results
    }

    normalized_results = []
    for sentence in sentences:
        sentence_id = sentence["sentence_id"]

        normalized_results.append({
            "sentence_id": sentence_id,
            "corrected_sentence": corrected_by_sentence_id.get(sentence_id),
            "human_corrected_sentence": None,
        })

    return normalized_results

def write_jsonl(file, record):
    file.write(json.dumps(record, ensure_ascii=False) + "\n")
    file.flush()

def _error_reviews(sentences):
    rows = []
    for sentence in sentences:
        entities = sentence.get("entities", []) or [{"entity_id": None}]
        for entity in entities:
            rows.append({
                "sentence_id": sentence["sentence_id"],
                "entity_id": entity.get("entity_id"),
                "target_span": entity.get("target_span"),
                "target_type": entity.get("target_type"),
                "corrected_span": None,
                "error_lv1": None,
                "error_lv2": None,
                "reason": None,
                "review_needed": True,
                "llm_review_status": "unreviewed",
                "review_status": "error",
            })
    return rows


def save_review_result(
    review_file,
    corrected_sentence_file,
    document,
    run_id,
    sentences,
    result=None,
):
    reviews = result["reviews"] if result else _error_reviews(sentences)
    corrected_sentences = result["corrected_sentences"] if result else [
        {
            "sentence_id": sentence["sentence_id"],
            "corrected_sentence": None,
            "human_corrected_sentence": None,
        }
        for sentence in sentences
    ]

    for review in reviews:
        write_jsonl(review_file, {
            "run_id": run_id,
            "doc_id": document["id"],
            **review,
        })

    for sentence in corrected_sentences:
        write_jsonl(corrected_sentence_file, {
            "run_id": run_id,
            "doc_id": document["id"],
            **sentence,
        })
