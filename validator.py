
import os
import json
from pathlib import Path
import re
from datetime import datetime, timezone

from dotenv import load_dotenv
from openai import OpenAI


#=========================================================
# 1. 설정
#=========================================================
load_dotenv()

API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL_NAME = "anthropic/claude-sonnet-5.5"
# openai/gpt-4.1
# openai/gpt-5.1
# openai/gpt-5.2
# openai/gpt-5.4
# anthropic/claude-sonnet-5.5
# anthropic/claude-haiku-5.5

BASE_DIR = Path(__file__).resolve().parent 
PROMPT_PATH = BASE_DIR / "NER_SYSTEM_PROMPT.md"  
OUTPUT_FILE = BASE_DIR / "ner_review_results.jsonl"

MAX_COMPLETION_TOKENS = 8000 # 출력 토큰 조절
REASONING_EFFORT = "medium" # 모델의 추론 강도 조절

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=API_KEY,
)

#=========================================================
# 2. 검수 프롬프트
#=========================================================
SYSTEM_PROMPT = PROMPT_PATH.read_text(encoding="utf-8-sig").strip()

#=========================================================
# 3. 출력 형식
#=========================================================
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "article_id": {"type": "string"},
        "status": {
            "type": "string",
            "enum": ["pass", "error_found", "review_required"]
        },
        "errors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "paragraph_id": {"type": "string"},
                    "sentence_id": {"type": "string"},
                    "error_type": {
                        "type": "string",
                        "enum": [
                            "tag_error",
                            "wrong_tagging",
                            "tagging_missing",
                            "span_error",
                            "etc_error"
                        ]
                    },
                    "error_type_lv2": {
                        "type": ["string", "null"],
                        # "enum": [
                        #     "null",
                        #     "span_expansion",
                        #     "span_reduction",
                        #     "tagging_split",
                        #     "tagging_merge",
                        #     "novel_error",
                        #     "mixed_error"
                        # ]
                    },
                    "original_text": {"type": "string"},
                    "current_tagging": {"type": "string"},
                    "corrected_tagging": {"type": "string"},
                    "reason": {"type": "string"},
                    "needs_human_review": {"type": "boolean"}
                },
                "required": [
                    "paragraph_id",
                    "sentence_id",
                    "error_type",
                    "error_type_lv2",
                    "original_text",
                    "current_tagging",
                    "corrected_tagging",
                    "reason",
                    "needs_human_review"
                ],
                "additionalProperties": False
            }
        },
        "review_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "paragraph_id": {"type": "string"},
                    "sentence_id": {"type": "string"},
                    "original_text": {"type": "string"},
                    "current_tagging": {"type": "string"},
                    "reason": {"type": "string"}
                },
                "required": [
                    "paragraph_id",
                    "sentence_id",
                    "original_text",
                    "current_tagging",
                    "reason"
                ],
                "additionalProperties": False
            }
        },
        "needs_human_review": {"type": "boolean"},
        "summary": {"type": "string"}
    },
    "required": [
        "article_id",
        "status",
        "errors",
        "review_items",
        "needs_human_review",
        "summary"
    ],
    "additionalProperties": False
}


def validate_result_consistency(result: dict, article_id: str) -> None:
    if result.get("article_id") != article_id:
        raise ValueError(
            f"기사 ID 불일치: 입력={article_id}, 응답={result.get('article_id')}"
        )

    allowed_lv2 = {
        "tag_error": {None},
        "wrong_tagging": {None},
        "tagging_missing": {None},
        "span_error": {
            "span_expansion", "span_reduction", "tagging_split", "tagging_merge"
        },
        "etc_error": {"novel_error", "mixed_error"},
    }

    for index, error in enumerate(result.get("errors", [])):
        error_type = error.get("error_type")
        error_type_lv2 = error.get("error_type_lv2")
        if error_type not in allowed_lv2:
            raise ValueError(
                f"허용되지 않은 error_type: errors[{index}]={error_type!r}"
            )
        if error_type_lv2 not in allowed_lv2[error_type]:
            raise ValueError(
                f"error_type과 error_type_lv2 조합이 올바르지 않습니다: "
                f"errors[{index}]={error_type!r}/{error_type_lv2!r}"
            )

    errors = result.get("errors", [])
    review_items = result.get("review_items", [])
    item_requires_review = any(
        error.get("needs_human_review", False) for error in errors
    )
    expected_needs_human_review = bool(review_items) or item_requires_review

    if result.get("needs_human_review") != expected_needs_human_review:
        raise ValueError(
            "needs_human_review 값이 errors/review_items 내용과 일치하지 않습니다."
        )

    if expected_needs_human_review:
        expected_status = "review_required"
    elif errors:
        expected_status = "error_found"
    else:
        expected_status = "pass"

    if result.get("status") != expected_status:
        raise ValueError(
            f"status 불일치: 예상={expected_status}, 응답={result.get('status')}"
        )


# =========================================================
# 4. 기사 검수 함수
# 하나의 document를 입력받아 검수
# =========================================================
def review_article(document: dict) -> dict:
    """
    입력:
    {
        "id": "NLRW2600000001.481",
        "paragraph": [
            {
                "id": "NLRW2600000001.481.1",
                "sentence": [
                    {
                        "id": "NLRW2600000001.481.1.1",
                        "form": "<양민혁: PS> ..."
                    }
                ]
            }
        ]
    }
    """

    article_id = document["id"]

    # 검수에 필요한 필드만 추출하되 원본 계층 구조 유지
    user_input = {
        "id": article_id,
        "paragraph": [
            {
                "id": paragraph["id"],
                "sentence": [
                    {
                        "id": sentence["id"],
                        "form": sentence["form"]
                    }
                    for sentence in paragraph["sentence"]
                ]
            }
            for paragraph in document["paragraph"]
        ]
    }

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": (
                    "다음 기사 전체의 NER 태깅을 검수해줘.\n"
                    "paragraph 및 sentence의 ID를 유지해. "
                    "확정된 오류는 errors에, 판단이 불확실한 사례는 review_items에 기록해.\n\n"
                    + json.dumps(
                        user_input,
                        ensure_ascii=False
                    )
                )
            }
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "ner_review_result",
                "strict": True,
                "schema": RESPONSE_SCHEMA
            }
        },
        max_completion_tokens=MAX_COMPLETION_TOKENS,
        extra_body={
            "usage": {"include": True},
            "provider": {"require_parameters": True},
            "reasoning": {"effort": REASONING_EFFORT}
        }
    )

    if not response.choices:
        raise ValueError(
            f"모델 응답 choices가 비어 있습니다: {article_id}"
        )

    choice = response.choices[0]
    content = choice.message.content

    if not content:
        raise ValueError(
            f"모델 응답 내용이 비어 있습니다. "
            f"article_id={article_id}, "
            f"finish_reason={choice.finish_reason}"
        )

    # JSON 파싱
    result = json.loads(content)
    validate_result_consistency(result, article_id)

    # 토큰 및 비용 정보
    usage = response.usage

    usage_data = {
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "cost_usd": None,
        "reasoning_tokens": None,
        "cached_prompt_tokens": None
    }

    if usage is not None:
        usage_dict = (
            usage.model_dump()
            if hasattr(usage, "model_dump")
            else {}
        )

        prompt_details = (
            usage_dict.get("prompt_tokens_details") or {}
        )
        completion_details = (
            usage_dict.get("completion_tokens_details") or {}
        )

        usage_data.update({
            "prompt_tokens": usage_dict.get("prompt_tokens"),
            "completion_tokens": usage_dict.get("completion_tokens"),
            "total_tokens": usage_dict.get("total_tokens"),
            "cost_usd": usage_dict.get("cost"),
            "reasoning_tokens": completion_details.get(
                "reasoning_tokens"
            ),
            "cached_prompt_tokens": prompt_details.get(
                "cached_tokens"
            )
        })

    # 저장용 결과
    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": MODEL_NAME,
        "article_id": article_id,
        "result": result,
        "usage": usage_data,
        "finish_reason": choice.finish_reason,
        "response_id": response.id
    }

    # JSONL 누적 저장
    with OUTPUT_FILE.open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(output, ensure_ascii=False) + "\n"
        )

    return output

# =========================================================
# 5. 실행 예시
# =========================================================
def run_test_articles(test_article: dict) -> list[dict]:
    """test_article["document"]의 각 기사를 개별 검수한다."""
    results = []

    for document in test_article["document"]:
        result = review_article(document)
        results.append(result)

        print(f"\n기사 ID: {result['article_id']}")
        print(json.dumps(result["result"], ensure_ascii=False, indent=2))
        print("사용량:", json.dumps(result["usage"], ensure_ascii=False))

    print(f"\n결과 저장 위치: {OUTPUT_FILE}")
    return results


if __name__ == "__main__":
    test_article = {
        "id": "NLRW2600000001",
        "document": [
                {
                    "id": "NLRW2600000001.481",
                    "paragraph": [
                        {
                            "id": "NLRW2600000001.481.1",
                            "sentence": [
                                {
                                    "id": "NLRW2600000001.481.1.1",
                                    "form": "<양민혁: PS>, <손흥민: PS>과 함께 <토트넘: OG> 1군 훈련 등장"
                                }
                            ]
                        },
                        {
                            "id": "NLRW2600000001.481.2",
                            "sentence": [
                                {
                                    "id": "NLRW2600000001.481.2.1",
                                    "form": "<토트넘: OG>, 공식 유튜브 채널 통해 영상 공개"
                                }
                            ]
                        },
                        {
                            "id": "NLRW2600000001.481.3",
                            "sentence": [
                                {
                                    "id": "NLRW2600000001.481.3.1",
                                    "form": "슈팅 연습과 미니게임 등 훈련하는 모습"
                                }
                            ]
                        },
                        {
                            "id": "NLRW2600000001.481.4",
                            "sentence": [
                                {
                                    "id": "NLRW2600000001.481.4.1",
                                    "form": "<EFL컵 4강전: EV> 앞두고 1군 선수들과 함께해 눈길"
                                }
                            ]
                        },
                        {
                            "id": "NLRW2600000001.481.5",
                            "sentence": [
                                {
                                    "id": "NLRW2600000001.481.5.1",
                                    "form": "<강원FC: OG> 출신 <양민혁: PS>이 <춘천: LC> 출신 캡틴 <손흥민: PS>과 함께 <잉글랜드: LC> 프로축구 <프리미어리그: EV>(<EPL: EV>) <토트넘 홋스퍼: OG>의 1군 훈련장에 모습을 드러내 눈길을 끈다."
                                }
                            ]
                        },
                        {
                            "id": "NLRW2600000001.481.6",
                            "sentence": [
                                {
                                    "id": "NLRW2600000001.481.6.1",
                                    "form": "<토트넘: OG>은 구단 공식 유튜브 채널을 통해 <지난 7일: DT>(이하 현지시간) <양민혁: PS>이 <손흥민: PS> 등 1군 선수단과 함께 훈련하는 영상을 공개했다."
                                },
                                {
                                    "id": "NLRW2600000001.481.6.2",
                                    "form": "영상에는 <양민혁: PS>이 선수단과 함께 슈팅 연습을 비롯한 간단한 미니게임 등에 참여하는 모습이 담겨 있다."
                                },
                                {
                                    "id": "NLRW2600000001.481.6.3",
                                    "form": "실내 훈련시설에서 <손흥민: PS>과 함께 몸풀기를 하는 모습도 나왔다."
                                }
                            ]
                        },
                        {
                            "id": "NLRW2600000001.481.7",
                            "sentence": [
                                {
                                    "id": "NLRW2600000001.481.7.1",
                                    "form": "<토트넘: OG>에게 중요한 경기인 <EFL컵: EV>(<카라바오컵: EV>) <4강전: EV>을 앞두고 <양민혁: PS>이 1군 선수단과 함께 훈련에 참여한 만큼 이 경기에서 처음으로 <양민혁: PS>이 <토트넘: OG> 벤치에 앉아 있는 모습을 포착할 수 있을지 관심이 집중된다."
                                },
                                {
                                    "id": "NLRW2600000001.481.7.2",
                                    "form": "경기를 뛰지 못하더라도 <양민혁: PS>은 빠르면 <오는 12일: DT> 오후 9시 30분 <잉글랜드: LC> <FA컵 3라운드: EV>(<64강: EV>)에서 맞붙는 5부리그 팀 <탬워스: OG>와의 경기에 출전해 데뷔전을 치를 수도 있을 것으로 기대된다."
                                },
                                {
                                    "id": "NLRW2600000001.481.7.3",
                                    "form": "<토트넘: OG>이 이 경기에서 어린 선수들이나 후보 선수들로 <탬워스전: EV>에 임한다면 출전할 가능성이 높다."
                                }
                            ]
                        },
                        {
                            "id": "NLRW2600000001.481.8",
                            "sentence": [
                                {
                                    "id": "NLRW2600000001.481.8.1",
                                    "form": "앞서 <양민혁: PS>은 <토트넘: OG>의 대우와 관련된 논란을 겪었다."
                                },
                                {
                                    "id": "NLRW2600000001.481.8.2",
                                    "form": "<토트넘: OG> 홈페이지에 <양민혁: PS>의 등번호와 이름이 <토트넘: OG> 등록되지 않아 유령 선수가 아니냐는 비판이 일었고 <안지 포스테코글루: PS> <토트넘: OG> 감독도 <양민혁: PS>과 관련된 인터뷰에서 “수준이 낮은 리그 출신”이라고 지칭하며 공분을 산 바 있다."
                                },
                                {
                                    "id": "NLRW2600000001.481.8.3",
                                    "form": "그러나 <토트넘: OG>의 이번 훈련 영상 공개를 통해 이 같은 논란은 어느 정도 종식될 것으로 예상된다."
                                }
                            ]
                        },
                        {
                            "id": "NLRW2600000001.481.9",
                            "sentence": [
                                {
                                    "id": "NLRW2600000001.481.9.1",
                                    "form": "한편 <토트넘: OG>은 <지난 7일: DT> <손흥민: PS>과의 계약을 <1년: DT> 연장하겠다고 발표했다."
                                },
                                {
                                    "id": "NLRW2600000001.481.9.2",
                                    "form": "이로써 <손흥민: PS>은 <오는 2026년 여름: DT>까지 <토트넘: OG>과 함께하게 됐다."
                                }
                            ]
                        }
                    ]
                }
            ]
    }
    run_test_articles(test_article)