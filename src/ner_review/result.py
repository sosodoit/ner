# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER 검수 결과 처리
# * 작성일: 2026-11-08
# * 수정일: 2026-11-11 (오류 행만 수신·정상 행 코드 생성, 출력 불변 조건 검사)
# * 설명: LLM 검수 결과 정규화 및 JSONL 결과 저장
# ***************************************************
import re
import json
import logging

TAG_PATTERN = re.compile(r"<([^<>]+?): (?:PS|LC|OG|AF|DT|EV)>")
MISS = "tagging_miss"


def safe_error_message(error):
    return f"{type(error).__name__}: request failed"

def strip_tags(text):
    return TAG_PATTERN.sub(r"\1", text)

# ***************************************************
# * 오류 행 검사
# * 필드·타입·허용값은 strict 스키마가 보장하므로 검사하지 않음
# * 스키마로 보장할 수 없는 ID 정합성과 출력 불변 조건만 검사
# ***************************************************
def _flag(review, label):
    review["review_needed"] = True
    review["reason"] = f"[자동검증:{label}] {review['reason']}"

def check_review(review, sentence, entity_ids, seen):
    """제외할 행은 사유 문자열, 유효한 행은 None 반환. 위반 행은 휴먼 검수 표시."""
    entity_id = review["entity_id"]
    if entity_id is None and review["error_lv1"] != MISS:
        return "null entity_id without tagging_miss"
    if entity_id is not None and entity_id not in entity_ids:
        return f"unknown entity_id: {entity_id}"
    if entity_id is not None and entity_id in seen:
        return f"duplicate entity_id: {entity_id}"
    if review["target_span"] not in sentence["text"]:
        return "target_span not found in sentence"
    if entity_id is not None and review["target_span"] != entity_ids[entity_id].get("target_span"):
        return f"target_span does not match entity_id: {entity_id}"
    if entity_id is None and review["target_span"] == review["corrected_span"]:
        return "tagging_miss without correction"
    if review["target_span"] == review["corrected_span"]:
        return "no change"  # 수정안 = 원문 → 정상 처리

    if review["target_span"] not in sentence["text"]:
        _flag(review, "구간 미일치")
    elif strip_tags(review["target_span"]) != strip_tags(review["corrected_span"]):
        _flag(review, "원문 변경")
    return None

# ***************************************************
# * 결과 정규화: 오류 행 + 미출력 개체의 정상 행
# ***************************************************
def _row(sentence_id, entity, status, llm_status, reason=None, review_needed=False):
    return {
        "sentence_id": sentence_id,
        "entity_id": entity.get("entity_id"),
        "target_type": entity.get("target_type"),
        "llm_review_status": llm_status,
        "review_status": status,
        "target_span": entity.get("target_span"),
        "corrected_span": None,
        "error_lv1": None,
        "error_lv2": None,
        "reason": reason,
        "review_needed": review_needed,
    }


def _validation_row(sentence_id, entity, problem):
    """검증 실패로 휴먼 검수가 필요한 개체 행을 만든다."""
    return _row(
        sentence_id,
        entity,
        "error",
        "reviewed",
        reason=f"[자동검증 실패] {problem}",
        review_needed=True,
    )


def build_result(response_data, sentences):
    sentence_by_id = {sentence["sentence_id"]: sentence for sentence in sentences}
    errors_by_sentence, warnings = {}, []
    has_unknown_sentence = False
    for review in response_data["reviews"]:
        if review["sentence_id"] not in sentence_by_id:
            warnings.append(f"unknown sentence_id: {review['sentence_id']}")
            has_unknown_sentence = True
            continue
        errors_by_sentence.setdefault(review["sentence_id"], []).append(dict(review))

    rows = []
    for sentence in sentences:
        sentence_id = sentence["sentence_id"]
        entities = sentence.get("entities", [])
        entity_by_id = {entity.get("entity_id"): entity for entity in entities}

        error_rows, miss_rows = {}, []
        validation_entity_ids = set()
        validation_sentence = has_unknown_sentence
        for review in errors_by_sentence.get(sentence_id, []):
            problem = check_review(review, sentence, entity_by_id, error_rows)
            if problem:
                if problem != "no change":
                    warnings.append(problem)
                    entity_id = review.get("entity_id")
                    if entity_id in entity_by_id:
                        validation_entity_ids.add(entity_id)
                    else:
                        validation_sentence = True
                continue
            entity = entity_by_id.get(review["entity_id"], {})
            review.update(
                target_type=entity.get("target_type"),
                llm_review_status="reviewed",
                review_status="error",
            )
            if review["entity_id"] is None:
                miss_rows.append(review)
            else:
                error_rows[review["entity_id"]] = review

        # 기존 개체: 오류 행이 없으면 정상
        for entity in entities:
            entity_id = entity.get("entity_id")
            if validation_sentence or entity_id in validation_entity_ids:
                rows.append(_validation_row(
                    sentence_id,
                    entity,
                    "LLM 검수 결과를 원본 개체와 안전하게 매칭하지 못함",
                ))
            else:
                rows.append(error_rows.get(entity_id) or _row(sentence_id, entity, "normal", "reviewed"))
        # 태그 없는 문장: 누락 행이 없으면 문장 단위 정상 행 1개
        if not entities and not miss_rows:
            if validation_sentence:
                rows.append(_validation_row(
                    sentence_id,
                    {"entity_id": None},
                    "LLM 검수 결과를 원본 문장과 안전하게 매칭하지 못함",
                ))
            else:
                rows.append(_row(sentence_id, {"entity_id": None}, "normal", "reviewed"))
        rows.extend(miss_rows)

    if warnings:
        logging.warning(f"검수 결과 행 제외 {len(warnings)}건: {warnings[:5]}")
    return {"reviews": rows}

def build_fallback_result(sentences):
    """검수 실패 문서도 개체 단위 결과를 보존한다."""
    return {
        "reviews": [
            _row(
                sentence["sentence_id"], entity, "error", "unreviewed",
                reason="LLM review failed; manual review required.",
                review_needed=True,
            )
            for sentence in sentences
            for entity in (sentence.get("entities", []) or [{"entity_id": None}])
        ],
    }

# ***************************************************
# * JSONL 저장
# ***************************************************
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

def save_review_result(review_file, document, run_id, sentences, result=None):
    result = result or build_fallback_result(sentences)
    for review in result["reviews"]:
        write_jsonl(review_file, {"run_id": run_id, "doc_id": document["id"], **review})
