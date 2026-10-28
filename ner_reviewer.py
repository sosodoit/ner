# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER Data Reviewer              
# * 작성일: 2026-10-22                 
# * 설명: NER 데이터 검수를 위한 메인 모듈  
# ***************************************************
import os
import json
import logging
from zoneinfo import ZoneInfo
from datetime import datetime
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()

from error_case_retriever import ERROR_LV1, ERROR_LV2
from error_case_retriever import load_error_cases, split_reviewed_sentences, convert_reviewed_cases, select_representative_cases, format_representative_cases

BASE_DIR = Path(__file__).resolve().parent
ANALYSIS_DIR = BASE_DIR / "analysis"
DATA_ROOT = BASE_DIR / "data"

DATA_VERSION = "poc_20261027_194000"
DATA_DIR = DATA_ROOT / DATA_VERSION
ID_DIR = DATA_DIR / "id"
RUN_ID = f"run_{datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y%m%d_%H%M%S')}"
OUTPUT_DIR = BASE_DIR / "outputs" / DATA_VERSION / RUN_ID

ERROR_CASES_FILE = ANALYSIS_DIR / "NER_개체명검수이력.xlsx"
PROMPT_DIR = BASE_DIR / "prompts"
LOG_FILE = BASE_DIR / "ner_reviewer.log"

# ***************************************************
# * API 설정
# * OPENAI: gpt-4.1, gpt-5.1, gpt-5.2, gpt-5.4
# * OPENROUTER: openai/gpt-4.1, openai/gpt-5.1, openai/gpt-5.2, openai/gpt-5.4, anthropic/claude-sonnet-5.5, anthropic/claude-haiku-5.5
# ***************************************************
API_PROVIDER = "OPENROUTER"
MODEL_NAME = "anthropic/claude-sonnet-5.5"

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
# ***************************************************
REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "sentence_id": {"type": "string"},        
        "review_status": {"type": "string", "enum": ["error", "normal"]},
        "target_span": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "corrected_span": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "error_lv1": {"anyOf": [{"type": "string", "enum": ERROR_LV1}, {"type": "null"}]},
        "error_lv2": {"anyOf": [{"type": "string", "enum": ERROR_LV2},{"type": "null"}]},
        "reason": {"type": "string"},
        "review_needed": {"type": "boolean"},
    },
    "required": ["sentence_id", "review_status", "target_span", "corrected_span", "error_lv1", "error_lv2", "reason", "review_needed"],
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
# * LLM 검수 & 결과 저장
# * 입력 형식: 문장ID, 문장텍스트, 검수상태, 대표사례
# * 출력 형식: 문장ID, 대상문장, 수정문장, 오류유형1, 오류유형2, 검수사유, 추가검수필요여부
# * - 검수대상 문장이 없으면 LLM 검수를 실행하지 않고 기존검수결과 저장
# * 입력 단위: 문서(document) 단위
# * 출력 단위: 문서(document) 단위
# * 출력 파일명: {언론사}.jsonl
# * - article : ner 태깅된 corpus4 json 파일
# ***************************************************
article_files = sorted(DATA_DIR.glob("*.json"))
error_cases = load_error_cases(ERROR_CASES_FILE)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

for input_file in article_files:

    id_file = ID_DIR / input_file.name
    output_file = OUTPUT_DIR / f"{input_file.stem}.jsonl"
    article = json.loads(input_file.read_text(encoding="utf-8-sig"))
    review_status = split_reviewed_sentences(input_file, id_file, error_cases)

    with output_file.open("w", encoding="utf-8") as f:
        for document in article["document"]:
            sentences = [{"sentence_id": sentence["id"], "text": sentence["form"]} for paragraph in document["paragraph"] for sentence in paragraph["sentence"]]
            document_status = review_status[document["id"]]
            reviewed_ids = {item["sentence_id"] for item in document_status["reviewed"]}
            
            # 미검수 문장과 유사한 대표사례 선택
            selected_cases = select_representative_cases(document_status["unreviewed"], error_cases)
            article_input = (
                "다음은 개체명 태깅 검수 대상 기사입니다.\n\n"
                + "\n".join(
                    f"[{('기존검수완료 - 결과유지' if sentence['sentence_id'] in reviewed_ids else '신규검수대상')}] "
                    f"[{sentence['sentence_id']}] {sentence['text']}"
                    for sentence in sentences
                )
            )
            article_input += "\n\n" + format_representative_cases(selected_cases)

            # 미검수 문장이 있을 때만 LLM 검수 실행
            if document_status["unreviewed"]:
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
                    }
                )
                llm_reviews = json.loads(response.output_text)["reviews"]
                # 기존검수문장에 대한 LLM 결과 제외
                llm_reviews = [review for review in llm_reviews if review["sentence_id"] not in reviewed_ids]
            else:
                llm_reviews = []

            # LLM이 오류 결과를 반환하지 않은 문장은 정상으로 기록
            returned_sentence_ids = {review["sentence_id"] for review in llm_reviews}
            for sentence in document_status["unreviewed"]:
                if sentence["sentence_id"] not in returned_sentence_ids:
                    llm_reviews.append({
                        "sentence_id": sentence["sentence_id"],
                        "review_status": "normal",
                        "target_span": None,
                        "corrected_span": None,
                        "error_lv1": None,
                        "error_lv2": None,
                        "reason": "오류 없음",
                        "review_needed": False,
                    })

            # 저장
            result = {"reviews": convert_reviewed_cases(document_status["reviewed"]) + llm_reviews}
            f.write(json.dumps({"doc_id": document["id"], "provider": API_PROVIDER, "model": MODEL_NAME, "result": result,}, ensure_ascii=False) + "\n")
            logging.info(f"검수완료: {document['id']}")

    logging.info(f"결과저장완료: {output_file}")
