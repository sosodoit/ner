# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER 검수 결과 처리
# * 작성일: 2026-11-08
# * 설명: LLM 검수 결과 정규화 및 JSONL 결과, 메타데이터 저장
# ***************************************************
import json

def safe_error_message(error):
    return f"{type(error).__name__}: request failed"

def validate_response_data(response_data, sentences):
    # 응답 형식 확인
    if not isinstance(response_data, dict):
        raise ValueError("response must be an object")
    if set(response_data) != {"reviews", "corrected_sentences"}:
        raise ValueError("invalid response fields")

    reviews = response_data.get("reviews")
    corrected_sentences = response_data.get("corrected_sentences")
    # 결과 배열 형식 확인
    if not isinstance(reviews, list) or not isinstance(corrected_sentences, list):
        raise ValueError("reviews and corrected_sentences must be arrays")

    sentence_ids = [sentence["sentence_id"] for sentence in sentences]
    sentence_id_set = set(sentence_ids)
    # 입력 문장 및 개체 ID 기준 생성
    expected_entity_keys = {
        (sentence["sentence_id"], entity.get("entity_id"))
        for sentence in sentences
        for entity in sentence.get("entities", [])
    }

    review_keys = []
    for review in reviews:
        # 검수 결과 형식 확인
        if not isinstance(review, dict):
            raise ValueError("review must be an object")
        required_fields = {
            "sentence_id", "entity_id", "review_status", "target_span",
            "corrected_span", "error_lv1", "error_lv2", "reason",
            "review_needed",
        }
        missing_fields = required_fields - review.keys()
        if missing_fields:
            raise ValueError(f"missing review fields: {sorted(missing_fields)}")
        if set(review) != required_fields:
            raise ValueError("invalid review fields")
        if not isinstance(review["sentence_id"], str):
            raise ValueError("invalid review sentence_id")
        if review["entity_id"] is not None and not isinstance(review["entity_id"], str):
            raise ValueError("invalid review entity_id")
        if not isinstance(review["review_status"], str) or review["review_status"] not in {"error", "normal"}:
            raise ValueError("invalid review_status")
        for field in ("target_span", "corrected_span", "error_lv1", "error_lv2"):
            if review[field] is not None and not isinstance(review[field], str):
                raise ValueError(f"invalid review {field}")
        if not isinstance(review["reason"], str):
            raise ValueError("invalid review reason")
        if not isinstance(review["review_needed"], bool):
            raise ValueError("invalid review_needed")
        key = (review.get("sentence_id"), review.get("entity_id"))
        review_keys.append(key)
        # 문장 ID 일치 확인
        if key[0] not in sentence_id_set:
            raise ValueError(f"unknown sentence_id: {key[0]}")
        # 개체 ID 일치 확인
        if key not in expected_entity_keys:
            raise ValueError(
                f"unknown entity_id: sentence_id={key[0]}, entity_id={key[1]}"
            )

    # 중복 개체 ID 확인
    if len(review_keys) != len(set(review_keys)):
        raise ValueError("duplicate review entity_id")

    # 누락 개체 ID 확인
    missing_entity_keys = expected_entity_keys - set(review_keys)
    if missing_entity_keys:
        raise ValueError(f"missing review entity_id: {sorted(missing_entity_keys, key=str)}")

    corrected_ids = []
    for item in corrected_sentences:
        # 수정 문장 결과 형식 확인
        if not isinstance(item, dict):
            raise ValueError("corrected_sentence must be an object")
        if set(item) != {"sentence_id", "corrected_sentence"}:
            raise ValueError("invalid corrected_sentence fields")
        sentence_id = item.get("sentence_id")
        corrected_ids.append(sentence_id)
        # 수정 문장 ID 일치 확인
        if sentence_id not in sentence_id_set:
            raise ValueError(f"unknown sentence_id: {sentence_id}")
        # 수정 문장 필드 확인
        if "corrected_sentence" not in item:
            raise ValueError(f"missing corrected_sentence: {sentence_id}")
        # 수정 문장 값 형식 확인
        if not isinstance(item["corrected_sentence"], str):
            raise ValueError(f"invalid corrected_sentence: {sentence_id}")

    # 중복 문장 ID 확인
    if len(corrected_ids) != len(set(corrected_ids)):
        raise ValueError("duplicate corrected sentence_id")

    # 누락 문장 ID 확인
    missing_sentence_ids = sentence_id_set - set(corrected_ids)
    if missing_sentence_ids:
        raise ValueError(f"missing corrected sentence_id: {sorted(missing_sentence_ids)}")

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

def build_result(response_data, sentences):
    # 응답 정합성 검증
    validate_response_data(response_data, sentences)

    # 검수 결과 정규화
    return {
        "reviews": normalize_reviews(response_data["reviews"], sentences),
        "corrected_sentences": normalize_sentences(
            response_data["corrected_sentences"],
            sentences,
        ),
    }

def write_jsonl(file, record):
    file.write(json.dumps(record, ensure_ascii=False) + "\n")
    file.flush()

def write_response_error(file, run_id, doc_id, error_type, error, raw_response=None):
    write_jsonl(file, {
        "run_id": run_id,
        "doc_id": doc_id,
        "error_type": error_type,
        "error_message": str(error),
        "raw_response": raw_response,
    })

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
