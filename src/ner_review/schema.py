# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER 검수 스키마 정의
# * 작성일: 2026-11-08
# * 설명: 검수 오류 유형과 LLM 응답 데이터 구조 정의
# ***************************************************
ERROR_LV1_MAP = {
    "태그오류": "tagging_error",
    "오태깅": "tagging_wrong",
    "태깅누락": "tagging_miss",
    "범위오류": "span_error",
    "기타": "etc",
}
ERROR_LV1 = list(ERROR_LV1_MAP.values())

ERROR_LV2_MAP = {
    "범위확장": "span_expansion",
    "범위축소": "span_reduction",
    "태깅분리": "span_tagging_split",
    "태깅병합": "span_tagging_merge",
}
ERROR_LV2 = list(ERROR_LV2_MAP.values())

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "sentence_id": {"type": "string"},
        "entity_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "review_status": {"type": "string", "enum": ["error", "normal"]},
        "target_span": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "corrected_span": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "error_lv1": {"anyOf": [{"type": "string", "enum": ERROR_LV1}, {"type": "null"}]},
        "error_lv2": {"anyOf": [{"type": "string", "enum": ERROR_LV2}, {"type": "null"}]},
        "reason": {"type": "string"},
        "review_needed": {"type": "boolean"},
    },
    "required": ["sentence_id", "entity_id", "review_status", "target_span", "corrected_span", "error_lv1", "error_lv2", "reason", "review_needed"],
    "additionalProperties": False,
}

CORRECTED_SENTENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "sentence_id": {"type": "string"},
        "corrected_sentence": {"type": "string"},
    },
    "required": ["sentence_id", "corrected_sentence"],
    "additionalProperties": False,
}

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "reviews": {
            "type": "array",
            "items": REVIEW_SCHEMA
        },
        "corrected_sentences": {
            "type": "array",
            "items": CORRECTED_SENTENCE_SCHEMA,
        }
    },
    "required": ["reviews", "corrected_sentences"],
    "additionalProperties": False,
}
