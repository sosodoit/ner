# decision.py
# Compare JEV and OpenAI Decision models through OpenRouter.
# Input: nested JSON or JSONL containing article/paragraph/sentence data.
# Output: one JSONL record per article, with sentence- and entity-level results.

import os
import re
import json
import time
import argparse
from pathlib import Path
from collections import defaultdict

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("OPENROUTER_API_KEY")
API_URL = "https://openrouter.ai/api/alpha/decisions"

MODELS = {
    "jev": "typesafe/jev-1.13",
    "openai_decision": "openai/gpt-6-luna-decisions",
}

MODEL_MAX_QUESTIONS = {
    "jev": 400,
    "openai_decision": 200,
}

BASE_DIR = Path(__file__).resolve().parent
PROMPT_PATH = BASE_DIR / "NER_SYSTEM_PROMPT.md"
OUTPUT_FILE = Path("decision_comparison.jsonl")
MAX_QUESTIONS_PER_REQUEST = 400

ERROR_TYPES = {
    "tag_error": "태그오류",
    "wrong_tagging": "오태깅",
    "missing_tagging": "태깅누락",
    "range_error": "범위오류",
    "split_tagging": "태깅분리",
}

# These error types are evaluated for an existing tagged entity.
ENTITY_ERROR_TYPES = (
    "tag_error",
    "wrong_tagging",
    "range_error",
    "split_tagging",
)

# Extract markup such as <제주도: OG>. If subtype labels are present,
# the top-level tag is retained (e.g. <홍길동: PS_PERSON> -> PS).
ENTITY_PATTERN = re.compile(
    r"<\s*([^<>:]+?)\s*:\s*(PS|LC|OG|AF|DT|EV)(?:_[A-Z0-9_]+)?\s*>"
)


def load_records(path: Path):
    """Load JSON/JSONL while handling UTF-8 BOM."""
    with path.open("r", encoding="utf-8-sig") as f:
        if path.suffix.lower() == ".jsonl":
            return [json.loads(line) for line in f if line.strip()]
        data = json.load(f)

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    raise ValueError("입력은 JSON 객체, JSON 배열 또는 JSONL이어야 합니다.")


def get_id(record, *keys, default=""):
    if isinstance(record, dict):
        for key in keys:
            value = record.get(key)
            if value is not None and str(value).strip():
                return str(value)
    return default


def make_entity_id(sentence_id, entity_index):
    """Stable ID: sentence ID + 1-based entity order within that sentence."""
    return f"{sentence_id}_{entity_index:03d}"


def get_text_field(sentence):
    """Find the sentence text field used by the input corpus."""
    for key in ("form", "text", "sentence_text", "content"):
        value = sentence.get(key) if isinstance(sentence, dict) else None
        if isinstance(value, str):
            return value
    return ""


def extract_entities(sentence_text, sentence_id):
    entities = []
    for index, match in enumerate(ENTITY_PATTERN.finditer(sentence_text), start=1):
        entities.append({
            "entity_id": make_entity_id(sentence_id, index),
            "entity_index": index,
            "entity_text": match.group(1).strip(),
            "current_tag": match.group(2),
            "matched_text": match.group(0),
        })
    return entities


def collect_sentences(article):
    """Recursively find sentence-like objects under an article record."""
    article_id = get_id(article, "id", "article_id", "document_id", default="article_unknown")
    document_id = get_id(article, "document_id", default=article_id)
    sentences = []
    seen = set()

    def walk(node, paragraph_id=""):
        if isinstance(node, list):
            for item in node:
                walk(item, paragraph_id)
            return
        if not isinstance(node, dict):
            return

        current_paragraph_id = paragraph_id
        if "paragraph" in node and node.get("id") is not None:
            current_paragraph_id = str(node["id"])

        sentence_text = get_text_field(node)
        sentence_id = get_id(node, "id", "sentence_id")
        # A sentence must have an ID and a text field, and must not be a
        # paragraph/article container. This avoids treating container forms as sentences.
        is_sentence = bool(
            sentence_id
            and sentence_text
            and "paragraph" not in node
            and "sentence" not in node
            and "document" not in node
        )

        if is_sentence:
            unique_key = (sentence_id, sentence_text)
            if unique_key not in seen:
                seen.add(unique_key)
                sentences.append({
                    "article_id": article_id,
                    "document_id": document_id,
                    "paragraph_id": current_paragraph_id,
                    "sentence_id": sentence_id,
                    "sentence_text": sentence_text,
                    "entities": extract_entities(sentence_text, sentence_id),
                })
            return

        for key, value in node.items():
            if key == "paragraph" and isinstance(value, list):
                for paragraph in value:
                    walk(paragraph, get_id(paragraph, "id", default=current_paragraph_id))
            elif key == "sentence" and isinstance(value, list):
                for sentence in value:
                    walk(sentence, current_paragraph_id)
            elif isinstance(value, (dict, list)):
                walk(value, current_paragraph_id)

    walk(article)
    return sentences


def split_input_into_articles(records):
    """Support corpus roots with document arrays and already-flat article records."""
    articles = []
    for record in records:
        if not isinstance(record, dict):
            continue
        nested_documents = record.get("document")
        if isinstance(nested_documents, list):
            root_id = get_id(record, "id", "document_id", default="")
            for nested in nested_documents:
                if isinstance(nested, dict):
                    item = dict(nested)
                    item.setdefault("document_id", root_id)
                    articles.append(item)
        else:
            articles.append(record)
    return articles


def load_system_instructions():
    if not PROMPT_PATH.exists():
        raise FileNotFoundError(
            f"검수 프롬프트 파일을 찾을 수 없습니다: {PROMPT_PATH}\n"
            "decision.py와 같은 폴더에 NER_SYSTEM_PROMPT.md를 두세요."
        )

    base_prompt = PROMPT_PATH.read_text(encoding="utf-8-sig").strip()
    decision_task = """

[Decision API 전용 작업 지시]
- 아래 질문에 지정된 대상 개체 또는 문장만 판정합니다.
- 질문마다 지정된 오류 유형이 명확하게 존재하는지를 독립적으로 평가합니다.
- 다른 개체의 오류를 현재 대상 개체의 오류로 판단하지 않습니다.
- 문맥과 제공된 태깅 지침을 근거로 판단하며, 근거 없는 추측은 하지 않습니다.
- 수정 태깅이나 수정 제안 문장을 작성하지 않습니다. 질문에서 요구하는 판정만 수행합니다.
- 반환 점수는 API의 원래 응답값으로 보존하며, 점수를 임의로 true/false로 변환하지 않습니다.
"""
    return base_prompt + decision_task


def make_question(question_id, error_key, target):
    label = ERROR_TYPES[error_key]

    if error_key == "missing_tagging":
        target_description = (
            f"대상 문장 ID: {target['sentence_id']}\n"
            f"대상 문장 원문: {target['sentence_text']}\n"
            f"현재 태깅 개체 목록: {json.dumps(target['entities'], ensure_ascii=False)}"
        )
        instructions = (
            f"다음 문장에 기존 태깅에서 누락된 개체명이 명확하게 존재하는지 판정하세요.\n"
            f"{target_description}\n"
            f"오류 유형: {label}. 문장에 실제로 등장하지만 현재 태깅되지 않은 개체만 고려하세요."
        )
    else:
        target_description = (
            f"대상 문장 ID: {target['sentence_id']}\n"
            f"대상 문장 원문: {target['sentence_text']}\n"
            f"대상 entity_id: {target['entity_id']}\n"
            f"대상 개체명: {target['entity_text']}\n"
            f"현재 태그: {target['current_tag']}\n"
            f"태깅된 표기: {target['matched_text']}"
        )
        instructions = (
            f"아래에 지정한 개체 하나만 대상으로 판정하세요.\n"
            f"{target_description}\n"
            f"오류 유형: {label}. 이 개체에 해당 오류가 명확하게 존재하는지 판단하세요."
        )

    return question_id, {
        "type": "noul",
        "instructions": instructions,
        "criteria": {
            "true": f"대상에 명확한 {label} 오류가 존재함",
            "false": f"대상에 명확한 {label} 오류가 확인되지 않음",
        },
    }


def get_answer_value(answer_obj):
    """Keep the returned value as-is; observed responses use the 'answer' key."""
    if not isinstance(answer_obj, dict):
        return answer_obj
    if "answer" in answer_obj:
        return answer_obj.get("answer")
    return answer_obj.get("noul")


def call_decision_batch(model, state, questions):
    payload = {
        "model": model,
        "state": state,
        "questions": questions,
    }
    response = requests.post(
        API_URL,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=180,
    )
    if not response.ok:
        # OpenRouter's response body usually explains which field/model contract failed.
        try:
            error_detail = json.dumps(response.json(), ensure_ascii=False)
        except ValueError:
            error_detail = response.text
        raise requests.HTTPError(
            f"HTTP {response.status_code} for model={model}: {error_detail}",
            response=response,
        )

    result = response.json()
    answers = result.get("answers", {})

    normalized_answers = {}
    for question_id in questions:
        answer_obj = answers.get(question_id)
        if isinstance(answer_obj, dict):
            normalized_answers[question_id] = {
                "answer": get_answer_value(answer_obj),
                "type": answer_obj.get("type"),
                "raw": answer_obj,
                "error": None,
            }
        else:
            normalized_answers[question_id] = {
                "answer": None,
                "type": None,
                "raw": answer_obj,
                "error": "응답에 해당 질문의 답변이 없습니다.",
            }

    return {
        "requested_model": model,
        "served_model": result.get("model"),
        "answers": normalized_answers,
        "usage": result.get("usage"),
        "error": None,
    }


def add_usage(total, usage):
    if not isinstance(usage, dict):
        return total
    for key, value in usage.items():
        if isinstance(value, (int, float)):
            total[key] = total.get(key, 0) + value
        elif key not in total:
            total[key] = value
    return total


def make_targets(sentences):
    """Create entity-level and sentence-level targets with stable IDs."""
    targets = []
    for sentence in sentences:
        for entity in sentence["entities"]:
            targets.append({
                "target_id": entity["entity_id"],
                "target_kind": "entity",
                "error_key": None,
                **{key: sentence[key] for key in (
                    "article_id", "document_id", "paragraph_id", "sentence_id", "sentence_text"
                )},
                **entity,
            })
        # Missing-tagging detection is sentence-level because the missing entity
        # does not yet have an entity_id.
        targets.append({
            "target_id": f"{sentence['sentence_id']}_missing",
            "target_kind": "sentence",
            "error_key": "missing_tagging",
            **{key: sentence[key] for key in (
                "article_id", "document_id", "paragraph_id", "sentence_id", "sentence_text", "entities"
            )},
        })
    return targets


def process_article(article, system_instructions, max_questions, selected_models):
    article_id = get_id(article, "id", "article_id", "document_id", default="article_unknown")
    document_id = get_id(article, "document_id", default=article_id)
    sentences = collect_sentences(article)

    article_result = {
        "article_id": article_id,
        "document_id": document_id,
        "sentences": [],
        "model_summary": {},
    }

    if not sentences:
        article_result["error"] = (
            "문장을 찾지 못했습니다. 입력 JSON의 문장 ID와 form/text 필드를 확인하세요."
        )
        return article_result

    sentence_results = {}
    entity_results = {}
    for sentence in sentences:
        sentence_results[sentence["sentence_id"]] = {
            "sentence_id": sentence["sentence_id"],
            "paragraph_id": sentence["paragraph_id"],
            "sentence_text": sentence["sentence_text"],
            "missing_tagging": {},
            "missing_tagging_agreement": None,
            "entities": [],
        }
        for entity in sentence["entities"]:
            item = {
                "entity_id": entity["entity_id"],
                "entity_index": entity["entity_index"],
                "entity_text": entity["entity_text"],
                "current_tag": entity["current_tag"],
                "matched_text": entity["matched_text"],
                "predictions": {name: {} for name in MODELS},
                "agreement": {},
            }
            sentence_results[sentence["sentence_id"]]["entities"].append(item)
            entity_results[entity["entity_id"]] = item

    targets = make_targets(sentences)
    # Map each generated question to its exact sentence/entity result destination.
    target_questions = []
    question_counter = 0
    for target in targets:
        applicable_errors = ("missing_tagging",) if target["target_kind"] == "sentence" else ENTITY_ERROR_TYPES
        for error_key in applicable_errors:
            question_counter += 1
            question_id = f"q{question_counter:06d}"
            _, question = make_question(question_id, error_key, target)
            target_questions.append({
                "question_id": question_id,
                "question": question,
                "target": target,
                "error_key": error_key,
            })

    # 모델별 질문 제한 설정
    model_max_questions = {
        "jev": 400,
        "openai_decision": 200,
    }

    model_usage = {name: {} for name in MODELS}
    model_meta = {
        name: {
            "requested_model": model,
            "served_models": [],
            "errors": [],
        }
        for name, model in MODELS.items()
    }

    for model_name, model_id in MODELS.items():
        # 모델별 최대 질문 수 적용
        batch_size = min(
            max_questions,
            model_max_questions.get(model_name, 200),
        )

        # 각 모델의 제한에 맞춰 질문 배치를 별도로 생성
        batches = [
            target_questions[i:i + batch_size]
            for i in range(0, len(target_questions), batch_size)
        ]

        for batch_index, batch in enumerate(batches, start=1):
            questions = {item["question_id"]: item["question"] for item in batch}
            state = {
                "검수지침": system_instructions,
                "기사데이터": article,
                "검수대상": [
                    {
                        "question_id": item["question_id"],
                        "target_id": item["target"]["target_id"],
                        "target_kind": item["target"]["target_kind"],
                        "sentence_id": item["target"]["sentence_id"],
                        "sentence_text": item["target"]["sentence_text"],
                        "entity_id": item["target"].get("entity_id"),
                        "entity_text": item["target"].get("entity_text"),
                        "current_tag": item["target"].get("current_tag"),
                    }
                    for item in batch
                ],
            }
            try:
                result = call_decision_batch(model_id, state, questions)
                if result.get("served_model"):
                    model_meta[model_name]["served_models"].append(result["served_model"])
                add_usage(model_usage[model_name], result.get("usage"))

                for item in batch:
                    answer = result["answers"].get(item["question_id"], {})
                    target = item["target"]
                    error_key = item["error_key"]
                    answer_payload = {
                        "answer": answer.get("answer"),
                        "type": answer.get("type"),
                        "error": answer.get("error"),
                    }
                    if target["target_kind"] == "sentence":
                        sentence_results[target["sentence_id"]]["missing_tagging"][model_name] = answer_payload
                    else:
                        entity_results[target["target_id"]]["predictions"][model_name][error_key] = answer_payload
            except Exception as exc:
                message = f"batch {batch_index}: {type(exc).__name__}: {exc}"
                model_meta[model_name]["errors"].append(message)
                for item in batch:
                    target = item["target"]
                    error_key = item["error_key"]
                    failed = {"answer": None, "type": None, "error": message}
                    if target["target_kind"] == "sentence":
                        sentence_results[target["sentence_id"]]["missing_tagging"][model_name] = failed
                    else:
                        entity_results[target["target_id"]]["predictions"][model_name][error_key] = failed
            time.sleep(0.3)

    # Compare returned values only. Since the API returns numeric scores in the
    # observed responses, these are agreement checks, not error/no-error decisions.
    for sentence_result in sentence_results.values():
        jev = sentence_result["missing_tagging"].get("jev", {}).get("answer")
        opn = sentence_result["missing_tagging"].get("openai_decision", {}).get("answer")
        if jev is not None and opn is not None:
            sentence_result["missing_tagging_agreement"] = jev == opn

    for entity_result in entity_results.values():
        for error_key in ENTITY_ERROR_TYPES:
            jev = entity_result["predictions"].get("jev", {}).get(error_key, {}).get("answer")
            opn = entity_result["predictions"].get("openai_decision", {}).get(error_key, {}).get("answer")
            entity_result["agreement"][error_key] = (
                jev == opn if jev is not None and opn is not None else None
            )

    article_result["sentences"] = list(sentence_results.values())
    for model_name, meta in model_meta.items():
        meta["served_models"] = sorted(set(meta["served_models"]))
        meta["usage"] = model_usage[model_name]
        article_result["model_summary"][model_name] = meta

    return article_result


def main():
    parser = argparse.ArgumentParser(
        description="Compare JEV and OpenAI Decision at sentence/entity level via OpenRouter."
    )
    parser.add_argument(
        "--model",
        choices=["jev", "openai_decision", "both"],
        default="both",
        help="실행 모델: jev, openai_decision, both",
    )
    parser.add_argument("input_file", help="입력 JSON 또는 JSONL 경로")
    parser.add_argument("--limit", type=int, default=100, help="처리할 article 수 (기본값: 100)")
    parser.add_argument("--output", default=str(OUTPUT_FILE), help="출력 JSONL 경로")
    parser.add_argument(
        "--max-questions",
        type=int,
        default=MAX_QUESTIONS_PER_REQUEST,
        help=f"요청당 질문 수 (1~{MAX_QUESTIONS_PER_REQUEST}, 기본값: {MAX_QUESTIONS_PER_REQUEST})",
    )
    args = parser.parse_args()

    if not API_KEY:
        raise RuntimeError(".env 파일에 OPENROUTER_API_KEY를 설정하세요.")
    if not 1 <= args.max_questions <= MAX_QUESTIONS_PER_REQUEST:
        raise ValueError(f"--max-questions는 1~{MAX_QUESTIONS_PER_REQUEST} 사이여야 합니다.")

    input_path = Path(args.input_file)
    records = load_records(input_path)
    articles = split_input_into_articles(records)[:args.limit]
    system_instructions = load_system_instructions()
    selected_models = (
        MODELS
        if args.model == "both"
        else {args.model: MODELS[args.model]}
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as out:
        for index, article in enumerate(articles, start=1):
            article_id = get_id(article, "id", "article_id", "document_id", default=f"article_{index}")
            print(f"[{index}/{len(articles)}] 시작: {article_id}")
            result = process_article(article, system_instructions, args.max_questions, selected_models)
            out.write(json.dumps(result, ensure_ascii=False) + "\n")
            out.flush()
            entity_count = sum(len(s.get("entities", [])) for s in result.get("sentences", []))
            print(f"[{index}/{len(articles)}] 완료: {article_id} | 문장 {len(result.get('sentences', []))}개 | 개체 {entity_count}개")

    print(f"완료: {len(articles)}개 기사")
    print(f"결과 파일: {output_path.resolve()}")


if __name__ == "__main__":
    main()
