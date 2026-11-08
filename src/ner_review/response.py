# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER LLM 검수 실행
# * 작성일: 2026-11-08
# * 설명: 룰 기반 필터링 데이터를 대상으로 기사별 LLM 검수
# ***************************************************
import os
import time
import json
import logging
import argparse
import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI
from pathlib import Path
from zoneinfo import ZoneInfo
from datetime import datetime
from langsmith import traceable
from langsmith.wrappers import wrap_openai
from .prompt import build_system_prompt
from .result import normalize_reviews, safe_error_message, save_review_result
from .schema import RESPONSE_SCHEMA

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_ROOT = BASE_DIR / "data"
PROMPT_DIR = BASE_DIR / "prompts"
LOG_FILE = BASE_DIR / "logs" / "ner_reviewer.log"

load_dotenv(BASE_DIR / ".env")
DATA_VERSION = os.getenv("DATA_VERSION")
API_PROVIDER = os.getenv("API_PROVIDER")
MODEL_NAME = os.getenv("MODEL_NAME")
PROMPT_VERSION = "ner-review-v2-entity-id"

# ***************************************************
# * 로그 설정
# ***************************************************
def configure_logging():
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )

# ***************************************************
# * API 클라이언트 생성
# ***************************************************
def create_client():
    if API_PROVIDER == "OPENAI":
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = None
    elif API_PROVIDER == "OPENROUTER":
        api_key = os.getenv("OPENROUTER_API_KEY")
        base_url = "https://openrouter.ai/api/v1"
    else:
        raise ValueError(f"지원하지 않는 API_PROVIDER: {API_PROVIDER}")

    client = OpenAI(
        api_key=api_key,
        **({"base_url": base_url} if base_url else {}),
    )
    return wrap_openai(client)

# ***************************************************
# * 모델 호출 함수 생성
# ***************************************************
def create_model_caller(client):
    @traceable(name="ner_review", run_type="chain")
    def call_model(instructions, article_input):
        try:
            return client.responses.create(
                model=MODEL_NAME,
                instructions=instructions,
                input=article_input,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "ner_response",
                        "strict": True,
                        "schema": RESPONSE_SCHEMA,
                    }
                }
            )
        except Exception:
            raise RuntimeError("LLM API request failed") from None
    return call_model

# ***************************************************
# * 기사 문장 추출
# ***************************************************
def extract_sentences(document):
    return [
        {
            "sentence_id": sentence["id"],
            "text": sentence["form"],
            "entities": sentence.get("entities", []),
        }
        for paragraph in document["paragraph"]
        for sentence in paragraph["sentence"]
    ]

# ***************************************************
# * 기사별 검수 입력 구성
# ***************************************************
def prepare_document(document):
    sentences = extract_sentences(document)

    sentence_blocks = []
    for item in sentences:
        entity_lines = [
            f"- entity_id: {entity['entity_id']} | "
            f"target_span: {entity['target_span']} | "
            f"target_type: {entity['target_type']}"
            for entity in item["entities"]
        ]
        entity_text = "\n".join(entity_lines) or "- 없음 (문장 단위 검수)"
        sentence_blocks.append(
            f"[{item['sentence_id']}] {item['text']}\n"
            f"검수 대상:\n{entity_text}"
        )

    article_input = (
        "# 개체명 태깅 검수 대상 기사:\n\n"
        + "\n".join(sentence_blocks)
    )

    system_prompt = build_system_prompt(PROMPT_DIR)
    logging.info(f"프롬프트 적용완료: 문서={document['id']}")

    return article_input, system_prompt, sentences

# ***************************************************
# * 기사별 LLM 검수
# ***************************************************
def review_file(input_file, output_root, run_id, data_version, call_model):
    outlet_dir = output_root / input_file.stem
    outlet_dir.mkdir(parents=True, exist_ok=True)

    output_file = outlet_dir / "reviews.jsonl"
    metadata_file = outlet_dir / "documents_meta.jsonl"
    if input_file.suffix in {".pkl", ".pickle"}:
        article = pd.read_pickle(input_file)
    else:
        article = json.loads(input_file.read_text(encoding="utf-8-sig"))

    with (output_file.open("w", encoding="utf-8") as result_file, metadata_file.open("w", encoding="utf-8") as metadata_output):
        for document in article["document"]:
            article_input, system_prompt, sentences = prepare_document(document)
            started_at = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
            started = time.perf_counter()

            try:
                response = call_model(system_prompt, article_input)
                reviews = json.loads(response.output_text)["reviews"]
                result = {"reviews": normalize_reviews(reviews, sentences)}
                
            except Exception as exc:
                save_review_result(
                    result_file,
                    metadata_output,
                    document,
                    input_file,
                    run_id,
                    started_at,
                    started,
                    sentences,
                    data_version,
                    API_PROVIDER,
                    MODEL_NAME,
                    PROMPT_VERSION,
                    error=exc,
                )
                logging.error(
                    f"LLM 검수 실패: {document['id']} | "
                    f"{safe_error_message(exc)} | 다음 문서로 진행"
                )
                continue

            save_review_result(
                result_file,
                metadata_output,
                document,
                input_file,
                run_id,
                started_at,
                started,
                sentences,
                data_version,
                API_PROVIDER,
                MODEL_NAME,
                PROMPT_VERSION,
                result=result,
            )
            logging.info(f"검수완료: {document['id']}")

    logging.info(f"결과저장완료: {outlet_dir}")

# ***************************************************
# * 검수 파이프라인 실행
# ***************************************************
def run_pipeline(data_version=None, rule_pickle=None):
    configure_logging()
    client = create_client()
    call_model = create_model_caller(client)
    run_id = f"run_{datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y%m%d_%H%M%S')}"

    if rule_pickle:
        rule_path = Path(rule_pickle)
        if rule_path.is_dir():
            input_files = sorted(rule_path.glob("*.pkl"))
            inferred_data_version = rule_path.parent.name
        else:
            input_files = [rule_path]
            inferred_data_version = rule_path.parent.parent.name
        data_version = data_version or inferred_data_version
    else:
        data_version = data_version or DATA_VERSION
        data_dir = DATA_ROOT / data_version
        input_files = sorted(data_dir.glob("*.json"))

    output_root = BASE_DIR / "outputs" / data_version / run_id / "reports"
    output_root.mkdir(parents=True, exist_ok=True)

    for input_file in input_files:
        review_file(input_file, output_root, run_id, data_version, call_model)

def main():
    parser = argparse.ArgumentParser(description="NER 개체명 태깅 검수")
    parser.add_argument("--data-version")
    parser.add_argument("--rule-pickle", type=Path, help="룰 검출 pickle 파일 또는 rule_review 폴더")
    args = parser.parse_args()

    # 검수 파이프라인 실행
    run_pipeline(args.data_version, args.rule_pickle)


if __name__ == "__main__":
    main()
