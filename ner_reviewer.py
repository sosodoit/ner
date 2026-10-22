# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER Data Reviewer              
# * 작성일: 2026-10-22                 
# * 설명: NER 데이터 검수를 위한 메인 모듈  
# ***************************************************
import os
import json
import logging
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
PROMPT_DIR = BASE_DIR / "prompts"
INPUT_FILE = BASE_DIR / "data" / "강원일보.json"
OUTPUT_FILE = BASE_DIR / "outputs" / "강원일보.jsonl"
LOG_FILE = BASE_DIR / "ner_reviewer.log"

# ***************************************************
# * API 설정
# * OPENAI: gpt-4.1, gpt-5.1, gpt-5.2, gpt-5.4
# * OPENROUTER: openai/gpt-4.1, openai/gpt-5.1, openai/gpt-5.2, openai/gpt-5.4, anthropic/claude-sonnet-5.5, anthropic/claude-haiku-5.5
# ***************************************************
API_PROVIDER = "OPENROUTER"
MODEL_NAME = "openai/gpt-4.1"

if API_PROVIDER == "OPENAI":
    API_KEY = os.getenv("SELECTSTART_OPENAI_API_KEY")
    BASE_URL = None
elif API_PROVIDER == "OPENROUTER":
    API_KEY = os.getenv("OPENROUTER_API_KEY")
    BASE_URL = "https://openrouter.ai/api/v1"
else:
    raise ValueError(f"지원하지 않는 API_PROVIDER: {API_PROVIDER}")

client = OpenAI(
    api_key=API_KEY,
    **({"base_url": BASE_URL} if BASE_URL else {}),
)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()])

# ***************************************************
# * 프롬프트
# * 공통 원칙: all.txt
# * 태그별 규칙: {tag}.txt
# * 예외 사항: {excepts}.txt
# * 오류 유형별 규칙: 미작성
# ***************************************************
read_prompt = lambda path: path.read_text(encoding="utf-8-sig").strip()

SYSTEM_PROMPT = "\n\n".join([
    read_prompt(PROMPT_DIR / "all.txt"),
    "\n".join(f"## {tag}\n{read_prompt(PROMPT_DIR / f'{tag}.txt')}" for tag in ["ps", "lc", "og", "af", "dt", "ev"]),
    "\n".join(f"## {excepts}\n{read_prompt(PROMPT_DIR / f'exception/{excepts}.txt')}" for excepts in ["common", "lean_word", "multilingual", "parentheses"]),
    read_prompt(PROMPT_DIR / "system_prompt.txt")
])

# ***************************************************
# * 출력(LLM 검수 결과) 스키마
# * 최종 출력 구조는 후처리에서 생성
# * ERROR_LV1: tagging_error = 태그오류, tagging_wrong = 오태깅, 
# *            tagging_miss = 태깅누락, span_error = 범위오류, etc = 기타
# * ERROR_LV2: span_expansion = 범위확장, span_reduction = 범위축소, 
# *            span_tagging_split = 태깅분리, span_tagging_merge = 태깅병합
# ***************************************************
ERROR_LV1 = [
    "tagging_error",
    "tagging_wrong",
    "tagging_miss",
    "span_error",
    "etc",
]

ERROR_LV2 = [
    "span_expansion",
    "span_reduction",
    "span_tagging_split",
    "span_tagging_merge"
]

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "sentence_id": {"type": "string"},        
        "target_span": {"type": "string"},
        "corrected_span": {"type": "string"},
        "error_lv1": {"type": "string", "enum": ERROR_LV1},
        "error_lv2": {"anyOf": [{"type": "string", "enum": ERROR_LV2},{"type": "null"}]},
        "reason": {"type": "string"},
        "review_needed": {"type": "boolean"},
    },
    "required": ["sentence_id", "target_span", "corrected_span", "error_lv1", "error_lv2", "reason", "review_needed"],
    "additionalProperties": False,
}

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "reviews": {"type": "array", "items": REVIEW_SCHEMA}
    },
    "required": ["reviews"],
    "additionalProperties": False,
}

# ***************************************************
# * 기사별 검수 및 LLM 결과 저장(JSONL)
# * 입력 형식: [문장 ID] 기존 태깅 문장
# * 입력 단위: 기사 (article : ner 태깅된 corpus4 json 파일)
# ***************************************************
article = json.loads(INPUT_FILE.read_text(encoding="utf-8-sig"))

with OUTPUT_FILE.open("w", encoding="utf-8") as f:
    for document in article["document"]:
        sentences = [{"sentence_id": sentence["id"], "text": sentence["form"]} for paragraph in document["paragraph"] for sentence in paragraph["sentence"]]
        article_input = (
            "다음은 개체명 태깅 검수 대상 기사입니다.\n\n"
            + "\n".join(f"[{sentence['sentence_id']}] {sentence['text']}" for sentence in sentences)
        )
        response = client.responses.create(
            model=MODEL_NAME,
            instructions=SYSTEM_PROMPT,
            input=article_input,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "ner_error_type_response",
                    "strict": True,
                    "schema": RESPONSE_SCHEMA,
                }
            },
        )

        result = json.loads(response.output_text)
        f.write(json.dumps({"doc_id": document["id"], "provider": API_PROVIDER, "model": MODEL_NAME, "result": result,}, ensure_ascii=False) + "\n")
        logging.info(f"검수완료: {document['id']}")

logging.info(f"결과저장완료: {OUTPUT_FILE}")