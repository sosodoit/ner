# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER LLM 검수 실행
# * 작성일: 2026-11-08
# * 설명: 룰 기반 필터링 데이터를 대상으로 기사별 LLM 검수
# ***************************************************
import os
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
from .result import (
    build_result,
    safe_error_message,
    save_review_result,
    write_jsonl,
    write_response_error,
)
from .schema import RESPONSE_SCHEMA
from .storage import build_parquet_rows, save_parquet_results, save_run_parquet

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_ROOT = BASE_DIR / "data"
PROMPT_DIR = BASE_DIR / "prompts"
LOG_FILE = BASE_DIR / "logs" / "ner_reviewer.log"

load_dotenv(BASE_DIR / ".env")
DATA_VERSION = os.getenv("DATA_VERSION")
API_PROVIDER = os.getenv("API_PROVIDER")
MODEL_NAME = os.getenv("MODEL_NAME")
PROMPT_VERSION = os.getenv("PROMPT_VERSION")

class ApiRequestError(RuntimeError):
    """LLM API 호출 실패."""

class ResponseParseError(ValueError):
    """LLM 응답 JSON 파싱 실패."""


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
            raise ApiRequestError("LLM API request failed") from None
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
def prepare_document(document, system_prompt=None):
    sentences = extract_sentences(document)

    # 기사 전체 원문 구성
    article_text = "\n".join(
        f"[{item['sentence_id']}] {item['text']}"
        for item in sentences
    )

    # 검수 대상 문장 구성
    review_blocks = []
    for item in sentences:
        if not item["entities"]:
            continue

        entity_lines = [
            f"- entity_id: {entity['entity_id']} | "
            f"target_span: {entity['target_span']} | "
            f"target_type: {entity['target_type']}"
            for entity in item["entities"]
        ]
        
        review_blocks.append(
            f"[{item['sentence_id']}] {item['text']}\n"
            f"검수 대상:\n" + "\n".join(entity_lines)
        )

    article_input = (
        "# ARTICLE\n"
        "다음은 기사의 전체 원문이다.\n\n"
        f"{article_text}\n\n"
        "# REVIEW_TARGETS\n"
        "다음은 문장별 대상과 기존 개체명 태깅 정보이다.\n"
        "모든 문장을 검수 대상으로 확인한다.\n\n"
        + ("\n\n".join(review_blocks) if review_blocks else "- 기존 태깅 없음")
        + "\n\n"
        "# REVIEW_GUIDELINES\n"
        "- 각 문장에 포함된 모든 개체명을 함께 확인하고 문장 전체 맥락에서 통합적으로 판단한다.\n"
        "- 동일 문장 내 개체명 간 관계와 태그 범위를 함께 고려한다.\n"
        "- 개체명별 검수 결과는 각 entity_id에 연결하여 반환한다.\n"
        "- 하나의 개체명 수정이 다른 개체명의 범위나 태그에 영향을 주는 경우 함께 검토한다.\n"
        "- 모든 개체명 검수 결과를 종합하여 해당 문장의 최종 수정 결과를 작성한다.\n"
        "- 최종 수정 문장은 검수 결과를 모두 반영하되, 오류가 없는 부분은 원문을 그대로 유지한다."
    )

    if system_prompt is None:
        system_prompt = build_system_prompt(PROMPT_DIR)
    logging.info(f"프롬프트 적용완료: 문서={document['id']}")

    return article_input, system_prompt, sentences

# ***************************************************
# * 기사별 LLM 검수
# ***************************************************
def review_file(input_file, output_root, run_id, data_version, call_model, system_prompt=None):
    outlet_dir = output_root / input_file.stem
    outlet_dir.mkdir(parents=True, exist_ok=True)

    output_file = outlet_dir / "reviews.jsonl"
    corrected_sentence_file = outlet_dir / "corrected_sentences.jsonl"
    response_error_file = outlet_dir / "response_errors.jsonl"
    review_rows = []
    corrected_sentence_rows = []
    if input_file.suffix in {".pkl", ".pickle"}:
        article = pd.read_pickle(input_file)
    else:
        article = json.loads(input_file.read_text(encoding="utf-8-sig"))

    with (
        output_file.open("w", encoding="utf-8") as result_file,
        corrected_sentence_file.open("w", encoding="utf-8") as corrected_output,
        response_error_file.open("w", encoding="utf-8") as error_output,
    ):
        for document in article["document"]:
            article_input, document_system_prompt, sentences = prepare_document(document, system_prompt)
            raw_response = None
            try:
                response = call_model(document_system_prompt, article_input)
                try:
                    raw_response = response.output_text
                except AttributeError as exc:
                    raise ResponseParseError("LLM response has no output_text") from exc
                try:
                    response_data = json.loads(raw_response)
                except (TypeError, json.JSONDecodeError) as exc:
                    raise ResponseParseError("LLM response is not valid JSON") from exc
                result = build_result(response_data, sentences)
            except Exception as exc:
                save_review_result(
                    result_file,
                    corrected_output,
                    document,
                    run_id,
                    sentences,
                )
                if isinstance(exc, ApiRequestError):
                    error_type = "API_ERROR"
                elif isinstance(exc, ResponseParseError):
                    error_type = "JSON_PARSE_ERROR"
                elif isinstance(exc, ValueError):
                    error_type = "VALIDATION_ERROR"
                else:
                    error_type = "POSTPROCESS_ERROR"
                write_response_error(
                    error_output,
                    run_id,
                    document["id"],
                    error_type,
                    exc,
                    raw_response,
                )
                logging.error(
                    f"LLM 검수 실패: {document['id']} | {error_type} | "
                    f"{safe_error_message(exc)} | 다음 문서로 진행"
                )
                continue

            current_review_rows, current_corrected_sentence_rows = build_parquet_rows(
                result,
                document,
                run_id,
                input_file.stem,
                datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat(),
            )
            review_rows.extend(current_review_rows)
            corrected_sentence_rows.extend(current_corrected_sentence_rows)

            save_review_result(
                result_file,
                corrected_output,
                document,
                run_id,
                sentences,
                result=result,
            )
            logging.info(f"검수완료: {document['id']}")

    save_parquet_results(outlet_dir, review_rows, corrected_sentence_rows)
    logging.info(f"결과저장완료: {outlet_dir}")

# ***************************************************
# * 검수 파이프라인 실행
# ***************************************************
def run_pipeline(data_version=None):
    configure_logging()
    client = create_client()
    call_model = create_model_caller(client)
    system_prompt = build_system_prompt(PROMPT_DIR)
    run_id = f"run_{datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y%m%d_%H%M%S')}"

    data_version = data_version or DATA_VERSION
    data_dir = DATA_ROOT / "filter" / "llm_input_data" / data_version
    if not data_dir.is_dir():
        data_dir = DATA_ROOT / data_version
    input_files = sorted(data_dir.glob("*.pkl"))

    output_root = BASE_DIR / "outputs" / data_version / run_id / "reports"
    output_root.mkdir(parents=True, exist_ok=True)

    run_file = output_root.parent / "run.jsonl"
    run_metadata = {
        "run_id": run_id,
        "provider": API_PROVIDER,
        "model": MODEL_NAME,
        "prompt_version": PROMPT_VERSION,
        "data_version": data_version,
        "load_dt": datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat(),
    }
    with run_file.open("w", encoding="utf-8") as output:
        write_jsonl(output, run_metadata)
    save_run_parquet(output_root.parent / "ner_runs.parquet", run_metadata)

    for input_file in input_files:
        review_file(input_file, output_root, run_id, data_version, call_model, system_prompt)

def main():
    parser = argparse.ArgumentParser(description="NER 개체명 태깅 검수")
    parser.add_argument("--data-version")
    args = parser.parse_args()

    # 검수 파이프라인 실행
    run_pipeline(args.data_version)


if __name__ == "__main__":
    main()
