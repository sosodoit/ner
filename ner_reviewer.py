# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER Data Reviewer              
# * 작성일: 2026-10-22                 
# * 설명: NER 데이터 검수를 위한 메인 모듈  
# ***************************************************
import os
import json
import re
import logging
import argparse
from zoneinfo import ZoneInfo
from datetime import datetime
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

from error_case_retriever import ERROR_LV1, ERROR_LV2
from error_case_retriever import load_error_cases, select_representative_cases, format_representative_cases
from error_case_retriever import load_mistag_dictionary, format_mistag_references

BASE_DIR = Path(__file__).resolve().parent
DATA_ROOT = BASE_DIR / "data"
PROMPT_DIR = BASE_DIR / "prompts"
ANALYSIS_DIR = BASE_DIR / "analysis"
ERROR_CASES_FILE = ANALYSIS_DIR / "NER_개체명검수이력.xlsx"
LOG_FILE = BASE_DIR / "ner_reviewer.log"

TAGS = ("ps", "lc", "og", "af", "dt", "ev")
ENTITY_TAG_PATTERN = re.compile(r"<[^:>]+:\s*(PS|LC|OG|AF|DT|EV)>", re.IGNORECASE)
TAG_TRIGGER_PATTERNS = {
    "ps": re.compile(r"대통령|장관|배우|가수|선수|작가|감독|후보|씨\b"),
    "lc": re.compile(r"(?:[가-힣]{2,}(?:시|도|군|구|동|강|섬|역)|한국|미국|중국|일본|서울|부산|제주|공원|공항)"),
    "og": re.compile(r"회사|기업|대학|학교|정부|국회|위원회|본부|공단|협회|병원|은행|정당|구단|대표팀|특검|검찰|경찰"),
    "af": re.compile(r"도서관|박물관|미술관|타워|다리|교량|도로|철도|선박|항공기|아이폰|작품|영화|소설|상품"),
    "dt": re.compile(r"\d{2,4}년|\d{1,2}월|\d{1,2}일|지난해|올해|내년|이번 주|지난주|다음 주|시대|계절|연말|연초"),
    "ev": re.compile(r"전쟁|혁명|사건|사고|참사|선거|대회|축제|회의|콘서트|올림픽|월드컵|토론|캠페인|운동|경기"),
}
TAG_CONFUSION_MAP = {
    "ps": {"og", "af"},
    "lc": {"og", "af"},
    "og": {"lc", "af"},
    "af": {"og", "lc"},
    "dt": {"ev"},
    "ev": {"dt", "og"},
}

# ***************************************************
# * 설정
# * DATA_VERSION: 검수 대상 데이터 폴더명
# * OPENAI: gpt-4.1, gpt-5.1, gpt-5.2, gpt-5.4
# * OPENROUTER: openai/gpt-4.1, openai/gpt-5.1, openai/gpt-5.2, openai/gpt-5.4, anthropic/claude-sonnet-5.5, anthropic/claude-haiku-5.5
# ***************************************************
DATA_VERSION = os.getenv("DATA_VERSION", "poc_20261029_194000")
API_PROVIDER = os.getenv("API_PROVIDER", "OPENAI")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4.1")

# ***************************************************
# * 프롬프트
# * 공통 원칙: all.txt
# * 태그별 규칙: {tag}.txt
# * 특수 상황: {excepts}.txt
# ***************************************************
read_prompt = lambda path: path.read_text(encoding="utf-8-sig").strip()

def build_system_prompt(article_text):
    existing_tags = {tag.lower() for tag in ENTITY_TAG_PATTERN.findall(article_text)}
    triggered_tags = set()
    for tag, pattern in TAG_TRIGGER_PATTERNS.items():
        if pattern.search(article_text):
            triggered_tags.add(tag)

    fallback = not triggered_tags
    if fallback:
        selected_tags = set(TAGS)
    else:
        selected_tags = existing_tags | triggered_tags
        for tag in existing_tags:
            selected_tags.update(TAG_CONFUSION_MAP.get(tag, set()))

    selected_exceptions = ["common"]
    if "(" in article_text or "（" in article_text: selected_exceptions.append("parentheses")
    if re.search(r"[A-Za-z]", article_text): selected_exceptions.append("multilingual")

    sections = [
        ("공통 판단 원칙", PROMPT_DIR / "all.txt"),
        *[(f"태그별 기준: {tag.upper()}", PROMPT_DIR / f"{tag}.txt") for tag in TAGS if tag in selected_tags],
        *[(f"특수 상황: {excepts}", PROMPT_DIR / f"exception/{excepts}.txt") for excepts in selected_exceptions],
        ("검수 실행 지침", PROMPT_DIR / "system_prompt.txt"),
    ]
    prompt = "\n\n".join(f"# {title}\n{read_prompt(path)}" for title, path in sections)
    return prompt, sorted(selected_tags), selected_exceptions, fallback

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
    "properties": {"reviews": {"type": "array", "items": REVIEW_SCHEMA}},
    "required": ["reviews"],
    "additionalProperties": False,
}


# ***************************************************
# * LLM 검수 & 결과 저장
# * 입력 단위: 문서(document) 단위
# * 출력 단위: 문서(document) 단위
# ***************************************************
def main():
    parser = argparse.ArgumentParser(description="NER 개체명 태깅 검수")
    parser.add_argument("--data-version", default=DATA_VERSION)
    args = parser.parse_args()

    load_dotenv(BASE_DIR / ".env")

    if API_PROVIDER == "OPENAI":
        api_key = os.getenv("SELECTSTART_OPENAI_API_KEY")
        base_url = None
    elif API_PROVIDER == "OPENROUTER":
        api_key = os.getenv("OPENROUTER_API_KEY")
        base_url = "https://openrouter.ai/api/v1"
    else:
        raise ValueError(f"지원하지 않는 API_PROVIDER: {API_PROVIDER}")

    client = OpenAI(api_key=api_key, **({"base_url": base_url} if base_url else {}))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()])

    data_dir = DATA_ROOT / args.data_version
    run_id = f"run_{datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y%m%d_%H%M%S')}"
    output_dir = BASE_DIR / "outputs" / args.data_version / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    article_files = sorted(data_dir.glob("*.json"))
    error_cases = load_error_cases(ERROR_CASES_FILE)
    mistag_dictionary = load_mistag_dictionary(ERROR_CASES_FILE)

    for input_file in article_files:
        output_file = output_dir / f"{input_file.stem}.jsonl"
        article = json.loads(input_file.read_text(encoding="utf-8-sig"))
        with output_file.open("w", encoding="utf-8") as f:
            for document in article["document"]:
                sentences = [
                    {"sentence_id": sentence["id"], "text": sentence["form"]}
                    for paragraph in document["paragraph"]
                    for sentence in paragraph["sentence"]
                ]
                selected_cases = select_representative_cases(sentences, error_cases)
                article_input = (
                    "다음은 개체명 태깅 검수 대상 기사입니다.\n\n"
                    + "\n".join(
                        f"[{sentence['sentence_id']}] {sentence['text']}"
                        for sentence in sentences
                    )
                )
                article_input += "\n\n" + format_representative_cases(selected_cases)
                prompt_source = article_input.split("\n\n[오류유형 대표사례 - 참고용]", 1)[0]
                system_prompt, selected_tags, selected_exceptions, prompt_fallback = build_system_prompt(prompt_source)
                mistag_references = format_mistag_references(prompt_source, mistag_dictionary)
                if mistag_references: system_prompt += "\n\n" + mistag_references
                logging.info(
                    f"프롬프트 선택완료: 문서={document['id']} | "
                    f"태그={','.join(selected_tags)} | "
                    f"예외={','.join(selected_exceptions)} | "
                    f"fallback={prompt_fallback} | 대표사례={len(selected_cases)}"
                )

                try:
                    response = client.responses.create(
                        model=MODEL_NAME,
                        instructions=system_prompt,
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
                    llm_reviews = json.loads(response.output_text)["reviews"]
                except Exception as exc:
                    logging.error(f"LLM 검수 실패: {document['id']} | {exc} | 다음 문서로 진행")
                    continue

                returned_sentence_ids = {review["sentence_id"] for review in llm_reviews}
                sentence_ids = {sentence["sentence_id"] for sentence in sentences}
                for sentence in sentences:
                    if sentence["sentence_id"] not in returned_sentence_ids:
                        llm_reviews.append({
                            "sentence_id": sentence["sentence_id"],
                            "review_status": "error",
                            "target_span": None,
                            "corrected_span": None,
                            "error_lv1": None,
                            "error_lv2": None,
                            "reason": "LLM 검수 결과 누락",
                            "review_needed": True,
                        })

                llm_reviews = [review for review in llm_reviews if review["sentence_id"] in sentence_ids]
                result = {"reviews": llm_reviews}
                f.write(json.dumps({"doc_id": document["id"], "provider": API_PROVIDER, "model": MODEL_NAME, "result": result}, ensure_ascii=False) + "\n")
                logging.info(f"검수완료: {document['id']}")

        logging.info(f"결과저장완료: {output_file}")


if __name__ == "__main__":
    main()

