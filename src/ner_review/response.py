# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER LLM 검수 실행
# * 작성일: 2026-11-08
# * 수정일: 2026-11-11 (입력 구성 정리, 오류 행만 수신, corrected_sentences 제거)
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
    strip_tags,
    build_fallback_result,
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
    elif API_PROVIDER == "CLAUDE":
        from anthropic import Anthropic

        return Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))
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
            if API_PROVIDER == "CLAUDE":
                return client.messages.create(
                    model=MODEL_NAME,
                    max_tokens=16384,
                    system=instructions,
                    messages=[
                        {"role": "user", "content": article_input},
                    ],
                    output_config={
                        "format": {
                            "type": "json_schema",
                            "schema": RESPONSE_SCHEMA,
                        }
                    },
                )

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
            "sentence_rule_evidence": sentence.get("sentence_rule_evidence", []),
        }
        for paragraph in document["paragraph"]
        for sentence in paragraph["sentence"]
    ]

# ***************************************************
# * 사전 근거 표기
# ***************************************************
def format_evidence(evidence):
    return json.dumps(evidence, ensure_ascii=False) if evidence else "없음"

# ***************************************************
# * 기사별 검수 입력 구성
# ***************************************************
def prepare_document(document, system_prompt=None):
    sentences = extract_sentences(document)

    # 기사 전체 원문 (태그 표기 제거, 문맥 판단용)
    article_text = "\n".join(
        f"[{item['sentence_id']}] {strip_tags(item['text'])}"
        for item in sentences
    )

    # 문장별 기존 태깅과 사전 근거 (target_span 복사 원천)
    review_blocks = []
    for item in sentences:
        entity_lines = [
            f"- entity_id: {entity['entity_id']} | "
            f"target_span: {entity['target_span']} | "
            f"target_type: {entity['target_type']} | "
            f"rule_evidence: {format_evidence(entity.get('rule_evidence'))}"
            for entity in item["entities"]
        ] or ["- entity_id: null | 기존 태깅 없음"]

        review_blocks.append(
            f"[{item['sentence_id']}] {item['text']}\n"
            f"sentence_rule_evidence: {format_evidence(item.get('sentence_rule_evidence'))}\n"
            + "\n".join(entity_lines)
        )

    article_input = (
        "# ARTICLE\n"
        f"{article_text}\n\n"
        "# REVIEW_TARGETS\n"
        + "\n\n".join(review_blocks)
    )

    if system_prompt is None:
        system_prompt = build_system_prompt(PROMPT_DIR)
    logging.info(f"프롬프트 적용완료: 문서={document['id']}")

    return article_input, system_prompt, sentences

# ***************************************************
# * 응답 텍스트 추출
# ***************************************************
def read_response_text(response):
    # 출력 한도 도달 등으로 응답이 잘리면 정상 미출력과 구분할 수 없으므로 실패 처리
    if getattr(response, "status", None) == "incomplete":
        raise ResponseParseError("LLM response incomplete")
    if API_PROVIDER == "CLAUDE":
        if getattr(response, "stop_reason", None) == "max_tokens":
            raise ResponseParseError("LLM response incomplete")
        for content in getattr(response, "content", []):
            if getattr(content, "type", None) == "text":
                return content.text
        raise ResponseParseError("Claude response has no text content")
    try:
        return response.output_text
    except AttributeError as exc:
        raise ResponseParseError("LLM response has no output_text") from exc

# ***************************************************
# * 기사별 LLM 검수
# ***************************************************
def review_file(input_file, output_root, run_id, data_version, call_model, system_prompt=None):
    outlet_dir = output_root / input_file.stem
    outlet_dir.mkdir(parents=True, exist_ok=True)

    output_file = outlet_dir / "reviews.jsonl"
    response_error_file = outlet_dir / "response_errors.jsonl"
    review_rows = []
    if input_file.suffix in {".pkl", ".pickle"}:
        article = pd.read_pickle(input_file)
    else:
        article = json.loads(input_file.read_text(encoding="utf-8-sig"))

    with (
        output_file.open("w", encoding="utf-8") as result_file,
        response_error_file.open("w", encoding="utf-8") as error_output,
    ):
        for document in article["document"]:
            article_input, document_system_prompt, sentences = prepare_document(document, system_prompt)
            raw_response = None
            load_dt = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
            try:
                response = call_model(document_system_prompt, article_input)
                raw_response = read_response_text(response)
                try:
                    response_data = json.loads(raw_response)
                except (TypeError, json.JSONDecodeError) as exc:
                    raise ResponseParseError("LLM response is not valid JSON") from exc
                result = build_result(response_data, sentences)
            except Exception as exc:
                result = build_fallback_result(sentences)
                review_rows.extend(build_parquet_rows(result, document, run_id, input_file.stem, load_dt))
                save_review_result(result_file, document, run_id, sentences, result=result)
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

            review_rows.extend(build_parquet_rows(result, document, run_id, input_file.stem, load_dt))
            save_review_result(result_file, document, run_id, sentences, result=result)
            logging.info(f"검수완료: {document['id']}")

    save_parquet_results(outlet_dir, review_rows)
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
    parser = argparse.ArgumentParser(description="NER 개체명 검수 실행")
    parser.add_argument("--data-version")
    args = parser.parse_args()

    run_pipeline(args.data_version)

if __name__ == "__main__":
    main()
