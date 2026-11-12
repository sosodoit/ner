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


__all__ = [
    "DECISION_SYSTEM_PROMPT",
    "DECISION_RULE_GUIDELINES",
    "SUBTAG_REFERENCE",
    "DECISION_QUESTIONS",
    "VALID_RULES",
    "SUBTAG_RULES",
    "build_decision_system_prompt",
    "build_decision_questions",
]
