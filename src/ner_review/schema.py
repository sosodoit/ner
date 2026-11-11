# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER 검수 스키마 정의
# * 작성일: 2026-11-08
# * 수정일: 2026-11-11 (오류 행만 출력, corrected_sentences 제거, 필드 순서·strict 요건 정비)
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
# LLM 출력 허용값: 'etc'는 휴먼 검수 전용
LLM_ERROR_LV1 = [v for v in ERROR_LV1 if v != "etc"]

ERROR_LV2_MAP = {
    "범위확장": "span_expansion",
    "범위축소": "span_reduction",
    "태깅분리": "span_tagging_split",
    "태깅병합": "span_tagging_merge",
}
ERROR_LV2 = list(ERROR_LV2_MAP.values())

NULLABLE_STRING = {"anyOf": [{"type": "string"}, {"type": "null"}]}

# LLM은 오류 행만 출력 (정상 미출력 → result.py에서 정상 처리)
# 오류 행이므로 수정안·오류 유형·근거는 null 불허
# 필드 순서 = 생성 순서: 수정안 → 오류 유형 → 근거 → 유보 여부
REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "sentence_id": {"type": "string"},
        "entity_id": NULLABLE_STRING,
        "target_span": {"type": "string"},
        "corrected_span": {"type": "string"},
        "error_lv1": {"type": "string", "enum": LLM_ERROR_LV1},
        "error_lv2": {"anyOf": [{"type": "string", "enum": ERROR_LV2}, {"type": "null"}]},
        "reason": {"type": "string"},
        "review_needed": {"type": "boolean"},
    },
    # strict 모드: 모든 property required
    "required": [
        "sentence_id", "entity_id", "target_span", "corrected_span",
        "error_lv1", "error_lv2", "reason", "review_needed",
    ],
    "additionalProperties": False,
}

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "reviews": {
            "type": "array",
            "items": REVIEW_SCHEMA,
        },
    },
    "required": ["reviews"],
    "additionalProperties": False,
}