# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER 검수 결과 처리
# * 작성일: 2026-11-08
# * 수정일: 2026-11-11 (오류 행만 수신·정상 행 코드 생성, 출력 불변 조건 검사)
# * 설명: LLM 검수 결과 정규화 및 JSONL 결과 저장
# ***************************************************
import hashlib
import json
import logging
import re
from pathlib import Path

POSTPROCESS_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
TAG_PATTERN = re.compile(r"<([^<>]+?): (?:PS|LC|OG|AF|DT|EV)>")
EDIT_TOKEN = re.compile(TAG_PATTERN.pattern + r"|[\s\S]")
DT_END_MARKER = re.compile(r"[ \t]*(부터|까지|중(?=$|[^\w]|에|인\b))")
DT_FREQUENCY = re.compile(r"에\s*(?:한\s*번|1\s*(?:번|회))")
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

def _source_window(text, tags, anchor, corrected):
    """수정안의 원문 문자열이 지정 ID를 감싸는 유일한 구간을 입력에서 복원한다."""
    plain = strip_tags(text)
    wanted = strip_tags(corrected)
    if not wanted:
        return None
    # 태그 내부의 글자를 자르는 경계는 원본 태그로 되돌릴 수 없다.
    boundaries = {}
    raw_end = plain_end = 0
    for tag in tags:
        start = plain_end + tag.start() - raw_end
        end = start + len(tag[1])
        if tag == anchor:
            anchor_start, anchor_end = start, end
        boundaries.update((p, raw_end + p - plain_end) for p in range(plain_end, start + 1))
        raw_end, plain_end = tag.end(), end
    boundaries.update((p, raw_end + p - plain_end) for p in range(plain_end, len(plain) + 1))
    windows = []
    pos = plain.find(wanted, max(0, anchor_end - len(wanted)))
    while 0 <= pos <= anchor_start:
        end = pos + len(wanted)
        if pos in boundaries and end in boundaries:
            windows.append((boundaries[pos], boundaries[end]))
        pos = plain.find(wanted, pos + 1)
    return windows[0] if len(windows) == 1 else None


def _normalize_edit(review, text, tags, anchor):
    corrected = review["corrected_span"]
    window = _source_window(text, tags, anchor, corrected)
    if window is None:
        return
    start, end = window
    source = text[start:end]
    if source == corrected:
        # ID를 포함한 원문과 태그가 모두 같으면 넓게 인용한 무변경 행이다.
        review["target_span"] = review["corrected_span"] = anchor[0]
        return
    # 모델이 함께 인용한 변경 없는 문맥을 제거한다. 기존 태그는 한 토큰으로 비교한다.
    left = [m[0] for m in EDIT_TOKEN.finditer(source)]
    right = [m[0] for m in EDIT_TOKEN.finditer(corrected)]
    while left and right and left[-1] == right[-1]:
        end -= len(left.pop())
        right.pop()
    prefix = 0
    for original, replacement in zip(left, right):
        if original != replacement:
            break
        start += len(original)
        prefix += 1
    if start <= anchor.start() and anchor.end() <= end:
        review["target_span"] = text[start:end]
        review["corrected_span"] = "".join(right[prefix:])


def _matches_edit_window(review, sentence, reviews):
    """기존 태그보다 넓은 수정 구간이 실제 ID 위치에 적용되는지 확인한다."""
    target = review["target_span"]
    corrected = review["corrected_span"]
    text = sentence["text"]
    if not target or strip_tags(target) != strip_tags(corrected):
        return False

    # 같은 표면형이 반복돼도 입력에 열거된 태그 순서로 실제 위치를 구분한다.
    tags = list(TAG_PATTERN.finditer(text))
    entities = sentence["entities"]
    if [tag[0] for tag in tags] != [entity["target_span"] for entity in entities]:
        return False
    anchor = next(tag for tag, entity in zip(tags, entities) if entity["entity_id"] == review["entity_id"])
    start = text.find(target, max(0, anchor.end() - len(target)))
    if start < 0 or start > anchor.start() or text.find(target, start + 1, anchor.start() + len(target)) >= 0:
        return False
    end = start + len(target)
    affected = {}
    for tag, entity in zip(tags, entities):
        if tag.start() < end and start < tag.end():
            if tag.start() < start or end < tag.end():
                return False
            affected[entity["entity_id"]] = tag
    if review["entity_id"] not in affected:
        return False

    anchor = affected[review["entity_id"]]
    kind = review["error_lv2"]
    if len(affected) == 1 and kind is None:
        # 조사 등 주변 원문까지 복사한 태그 제거·교체는 해당 태그만 달라야 한다.
        if review["error_lv1"] == "tagging_wrong":
            return corrected == target.replace(anchor[0], anchor[1], 1)
        replacements = list(TAG_PATTERN.finditer(corrected))
        return (review["error_lv1"] == "tagging_error" and len(replacements) == 1
                and replacements[0][1] == anchor[1] and replacements[0][0] != anchor[0]
                and corrected == target.replace(anchor[0], replacements[0][0], 1))

    # 확장·병합은 영향받는 최소 구간 전체가 수정 후 하나의 태그가 된다.
    if review["error_lv1"] not in {"span_error", "tagging_error"} or not TAG_PATTERN.fullmatch(corrected):
        return False
    if len(affected) == 1:
        return kind == "span_expansion"
    if kind not in {"span_tagging_merge", "span_expansion"}:
        return False
    # 일부 ID 누락, 중복, 서로 다른 수정안은 어느 쪽도 병합으로 채택하지 않는다.
    peers = [row for row in reviews if row["entity_id"] in affected]
    return (len(peers) == len(affected) and {row["entity_id"] for row in peers} == affected.keys()
            and all(row["target_span"] == target and row["corrected_span"] == corrected
                    and row["error_lv2"] == kind and row["error_lv1"] == review["error_lv1"]
                    for row in peers))


def check_review(review, sentence, entity_ids, seen, reviews=()):
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
        if not _matches_edit_window(review, sentence, reviews):
            return f"target_span does not match entity_id: {entity_id}"
    if entity_id is None and review["target_span"] == review["corrected_span"]:
        return "tagging_miss without correction"
    if review["target_span"] == review["corrected_span"]:
        return "no change"  # 수정안 = 원문 → 정상 처리

    if strip_tags(review["target_span"]) != strip_tags(review["corrected_span"]):
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


def _omitted_dt_reason(text, anchor):
    """모델이 생략한 DT 중 입력 위치에서 직접 확인할 수 있는 후보."""
    marker = DT_END_MARKER.match(text, anchor.end())
    if marker:
        return f"태그 뒤 '{marker[1]}'의 DT 범위 확인"
    if re.search(r"(?<!\w)오는\s+$", text[:anchor.start()]):
        return "태그 앞 '오는'의 DT 범위 확인"
    if re.fullmatch(r"\d+\s*일\s*차", anchor[1]):
        return "순번 'N일차'의 DT 태그 제거 여부 확인"
    return None


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
        is_target = "decision" not in sentence or (sentence.get("decision") or {}).get("review_candidate") is True

        error_rows, miss_rows = {}, []
        validation_entity_ids = set()
        validation_sentence = has_unknown_sentence
        sentence_reviews = errors_by_sentence.get(sentence_id, [])
        anchors = {}
        if entities and (is_target or sentence_reviews):
            tags = list(TAG_PATTERN.finditer(sentence["text"]))
            if [tag[0] for tag in tags] == [e["target_span"] for e in entities]:
                anchors = {e["entity_id"]: tag for e, tag in zip(entities, tags)}
                # 병합 참여 행도 같은 입력 구간으로 정규화한 뒤 함께 검사한다.
                for review in sentence_reviews:
                    anchor = anchors.get(review["entity_id"])
                    if anchor is not None:
                        _normalize_edit(review, sentence["text"], tags, anchor)
        for review in sentence_reviews:
            problem = check_review(review, sentence, entity_by_id, error_rows, sentence_reviews)
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

        # 모델이 생략한 DT도 원문의 해당 ID 위치에서 경계·순번을 확인한다.
        for entity in entities:
            entity_id = entity.get("entity_id")
            if validation_sentence or entity_id in validation_entity_ids:
                rows.append(_validation_row(
                    sentence_id,
                    entity,
                    "LLM 검수 결과를 원본 개체와 안전하게 매칭하지 못함",
                ))
                continue
            row = error_rows.get(entity_id)
            anchor = anchors.get(entity_id)
            if is_target and anchor is not None and entity.get("target_type") == "DT":
                if row is None:
                    reason = _omitted_dt_reason(sentence["text"], anchor)
                    if reason:
                        row = _row(sentence_id, entity, "error", "reviewed",
                                   f"[자동점검:DT 미출력] {reason}", review_needed=True)
                elif (row["error_lv1"] == "tagging_wrong"
                      and re.fullmatch(r"\d+\s*(?:년|개월|달|주|일)", anchor[1])
                      and DT_FREQUENCY.match(sentence["text"], anchor.end())):
                    _flag(row, "수치 기간의 반복 주기 해석")
            rows.append(row or _row(sentence_id, entity, "normal", "reviewed"))
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
