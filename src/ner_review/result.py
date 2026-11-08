# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER 검수 결과 처리
# * 작성일: 2026-11-08
# * 설명: LLM 검수 결과 정규화 및 JSONL 결과, 메타데이터 저장
# ***************************************************
import json
import time

def safe_error_message(error):
    return f"{type(error).__name__}: request failed"

def normalize_reviews(results, sentences):
    # LLM 결과를 원문 순서에 맞춰 재정렬
    reviews_by_sentence_id = {}
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
                    "llm_review_status": "unreviewed",
                    "review_status": "error",
                    "target_span": None,
                    "corrected_span": None,
                    "error_lv1": None,
                    "error_lv2": None,
                    "reason": None,
                    "review_needed": True,
                    "entities": entities,
                })
            continue

        # 결과를 반환한 각 검수 행을 reviewed로 표시
        for review in sentence_reviews:
            normalized_review = dict(review)
            normalized_review.setdefault("entity_id", None)
            normalized_review["llm_review_status"] = "reviewed"
            normalized_review["entities"] = entities
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
                "llm_review_status": "unreviewed",
                "review_status": "error",
                "target_span": None,
                "corrected_span": None,
                "error_lv1": None,
                "error_lv2": None,
                "reason": None,
                "review_needed": True,
                "entities": entities,
            })

    return normalized_results

def write_jsonl(file, record):
    file.write(json.dumps(record, ensure_ascii=False) + "\n")
    file.flush()

def save_review_result(
    result_file,
    metadata_file,
    document,
    input_file,
    run_id,
    started_at,
    started,
    sentences,
    dataset_version,
    provider,
    model,
    prompt_version,
    result=None,
    error=None,
):
    is_success = error is None

    if is_success:
        write_jsonl(result_file, {
            "run_id": run_id,
            "dataset_version": dataset_version,
            "press": input_file.stem,
            "doc_id": document["id"],
            "provider": provider,
            "model": model,
            "prompt_version": prompt_version,
            "status": "success",
            "result": result,
        })

    llm_review_status = "unreviewed"
    if is_success and result["reviews"] and all(review["llm_review_status"] == "reviewed" for review in result["reviews"]):
        llm_review_status = "reviewed"

    write_jsonl(metadata_file, {
        "doc_id": document["id"],
        "run_id": run_id,
        "started_at": started_at,
        "provider": provider,
        "model": model,
        "n_sentences": len(sentences),
        "latency_sec": time.perf_counter() - started,
        "status": "success" if is_success else "error",
        "error": safe_error_message(error) if error else None,
        "llm_review_status": llm_review_status,
        "prompt_version": prompt_version,
    })
