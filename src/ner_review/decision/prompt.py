# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: prompt.py
# * 설명: Decisions API 프롬프트 파일 로딩 및 질문 구성
# ***************************************************

import re
from pathlib import Path
from typing import Iterable


BASE_DIR = Path(__file__).resolve().parents[3]
PROMPT_DIR = BASE_DIR / "prompts" / "decision"

SYSTEM_PROMPT_FILE = "system_prompt.md"
RULES_GUIDELINE_FILE = "rules_guideline.md"
SUBTAGS_REFERENCE_FILE = "subtags_reference.md"


def _read_prompt(filename: str) -> str:
    return (PROMPT_DIR / filename).read_text(encoding="utf-8-sig").strip()


def _read_rule_guidelines() -> dict[str, str]:
    text = _read_prompt(RULES_GUIDELINE_FILE)
    matches = list(re.finditer(r"(?m)^#\s+(LLM_[ES]\d{3})\b", text))
    guidelines = {}

    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        guidelines[match.group(1)] = text[match.start():end].strip()

    return guidelines


DECISION_SYSTEM_PROMPT = _read_prompt(SYSTEM_PROMPT_FILE)
DECISION_RULE_GUIDELINES = _read_rule_guidelines()
SUBTAG_REFERENCE = _read_prompt(SUBTAGS_REFERENCE_FILE)


DECISION_QUESTIONS = {
    "LLM_E001": (
        "제공된 검수 대상 문장에 포함된 기존 태깅 표현 중, "
        "문맥상 특정 대상을 지칭하지 않거나 태깅 제외 대상에 해당하는 표현이 하나 이상 있는가?"
    ),
    "LLM_E002": (
        "제공된 검수 대상 문장에 포함된 기존 태깅 표현 중, "
        "실제 지칭 대상의 대분류와 기존에 부착된 태그의 대분류가 서로 다른 표현이 하나 이상 있는가?"
    ),
    "LLM_E003": (
        "제공된 검수 대상 문장에 포함된 기존 태깅 중, "
        "태그 범위의 축소·확장 또는 태깅 분리가 필요한 사례가 하나 이상 있는가?"
    ),
    "LLM_S001": (
        "제공된 검수 대상 문장에서 서로 인접한 둘 이상의 태그를 "
        "하나의 개체명으로 병합해야 하는 경우가 있는가?"
    ),
}

VALID_RULES = tuple(DECISION_QUESTIONS)
SUBTAG_RULES = {"LLM_E001", "LLM_E002"}

# 배치 실행용 질문은 기존의 네 개 세부 룰 질문과 분리한다. Decisions API는
# 텍스트를 생성하지 않으므로 한 문장당 Boolean choice 질문 두 개만 보낸다.
# 세부 대상/수정안/근거는 API 응답에 없는 값을 추정하지 않고 결과에서 null로 둔다.
BATCH_DECISION_QUESTIONS = {
    "tagging_error": (
        "검수 대상 문장의 기존 태깅 전체를 문맥으로 확인한다. 가장 먼저 기존 대분류 태그가 실제 지칭 대상과 "
        "불일치하는지 판단한다. 특히 LC(장소)·OG(기관/단체)·AF(인공물/작품)의 경합은 단어 표면형이 아니라 "
        "행위 주체·운영 주체·소재지·건축물/시설·작품 의미를 구분하여 판단한다. 대분류 오류가 없을 때만 "
        "오태깅 또는 범위 오류를 보조적으로 확인한다. 근거가 부족하거나 단순한 표면형 차이뿐이면 정상으로 선택한다."
    ),
    "tagging_merge": (
        "검수 대상 문장의 인접한 둘 이상의 기존 태그가 문맥상 하나의 정식 개체명·날짜·시설명 등을 "
        "구성하여 하나로 병합되어야 하는지 판단한다. 단순히 인접하거나 각자 독립적인 개체명이면 FALSE이다. "
        "이 판단은 기존 태그 내부의 범위 오류와 구분한다."
    ),
}


def _select_rules(rule_ids: Iterable[str]) -> list[str]:
    selected_rules = list(dict.fromkeys(rule_ids))
    invalid_rules = set(selected_rules) - set(VALID_RULES)

    if invalid_rules:
        raise ValueError(f"지원하지 않는 검수 룰: {sorted(invalid_rules)}")

    return selected_rules


def build_decision_system_prompt(rule_ids: Iterable[str]) -> str:
    """선택한 검수 룰에 필요한 시스템 프롬프트를 조립한다."""
    selected_rules = _select_rules(rule_ids)
    if not selected_rules:
        raise ValueError("최소 하나 이상의 검수 룰이 필요하다.")

    parts = [DECISION_SYSTEM_PROMPT]
    parts.extend(DECISION_RULE_GUIDELINES[rule_id] for rule_id in selected_rules)

    if SUBTAG_RULES.intersection(selected_rules):
        parts.append(SUBTAG_REFERENCE)

    return "\n\n".join(parts)


def build_decision_questions(sentence_id: str, rule_ids: Iterable[str]) -> list[dict]:
    """문장 ID와 검수 룰에 맞는 Decisions API Choice 질문을 생성한다."""
    selected_rules = _select_rules(rule_ids)
    if not sentence_id:
        raise ValueError("sentence_id가 비어 있다.")

    return [
        {
            "type": "choice",
            "name": f"{sentence_id}__{rule_id}",
            "instructions": DECISION_QUESTIONS[rule_id],
            "choices": [
                {"value": True, "description": "해당 오류가 하나 이상 존재함"},
                {"value": False, "description": "해당 오류가 존재하지 않음"},
            ],
        }
        for rule_id in selected_rules
    ]


def build_batch_decision_questions(sentence_id: str) -> list[dict]:
    """문장당 태그 오류/병합 필요 여부만 묻는 최소 질문 세트를 만든다."""
    if not sentence_id:
        raise ValueError("sentence_id가 비어 있다.")
    questions = []
    for question_id, instructions in BATCH_DECISION_QUESTIONS.items():
        if question_id == "tagging_error":
            choices = [
                {"value": "wrong_major_tag", "description": "문맥상 기존 대분류 태그가 잘못됨. 특히 LC·OG·AF 경합 오류."},
                {"value": "other_tagging_error", "description": "대분류 오류는 아니지만 명확한 오태깅 또는 범위 오류가 있음."},
                {"value": "normal", "description": "태그 오류가 없거나 근거가 부족함."},
            ]
        else:
            choices = [
                {"value": True, "description": "명확한 병합 필요가 있는 경우에만 TRUE"},
                {"value": False, "description": "병합 불필요 또는 근거 부족인 경우 FALSE"},
            ]
        questions.append({
            "type": "choice",
            "name": f"{sentence_id}__{question_id}",
            "instructions": instructions,
            "choices": choices,
        })
    return questions


__all__ = [
    "DECISION_SYSTEM_PROMPT",
    "DECISION_RULE_GUIDELINES",
    "SUBTAG_REFERENCE",
    "DECISION_QUESTIONS",
    "VALID_RULES",
    "SUBTAG_RULES",
    "BATCH_DECISION_QUESTIONS",
    "build_decision_system_prompt",
    "build_decision_questions",
    "build_batch_decision_questions",
    "build_batch_decision_system_prompt",
]


def build_batch_decision_system_prompt() -> str:
    """배치 질문에 필요한 공통 기준과 두 판단 기준만 조립한다."""
    parts = [DECISION_SYSTEM_PROMPT]
    parts.extend(DECISION_RULE_GUIDELINES[rule_id] for rule_id in ("LLM_E001", "LLM_E002", "LLM_E003", "LLM_S001"))
    parts.append(SUBTAG_REFERENCE)
    parts.append(
        "# 배치 출력 보조 원칙\n"
        "- 태그 오류 판단과 태깅 병합 판단은 서로 독립적으로 수행한다.\n"
        "- 태그 오류는 우선 LLM_E002 대분류 오류를 판단한다. LC·OG·AF 경합은 행위 주체/운영 주체/소재지/시설·작품 의미를 문맥으로 구분한다. 대분류 오류가 없을 때만 E001/E003을 보조적으로 판단한다.\n"
        "- 병합 판단은 LLM_S001 기준만 적용하며, 기존 태그 하나의 범위 수정은 병합으로 세지 않는다.\n"
        "- 활성 룰은 후보 근거로만 사용하고, 룰 검출 자체를 오류 확정 근거로 사용하지 않는다.\n"
        "- Decisions API는 텍스트 생성 API가 아니므로 choice 외의 설명·수정안·대상 태그를 생성하려 하지 않는다."
    )
    return "\n\n".join(parts)
