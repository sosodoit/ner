# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: LangSmith 사용량 추적
# * 작성일: 2026-11-08
# * 설명: 토큰 사용량, 비용 및 실행 시간 조회 및 저장
# ***************************************************
import os
import csv
import asyncio
import argparse
from dotenv import load_dotenv
from pathlib import Path
from datetime import datetime, timedelta, timezone
from langsmith import Client

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_PATH = BASE_DIR / "outputs" / "langsmith_usage.csv"

CSV_FIELDS = [
    "start_time",
    "run_id",
    "project_name",
    "model",
    "status",
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "cache_write_tokens",
    "total_tokens",
    "total_cost",
    "input_cost",
    "output_cost",
    "duration_seconds",
]

# ***************************************************
# * 토큰 사용량 추출
# ***************************************************
def find_usage(value):
    if isinstance(value, dict):
        for key in ("usage", "usage_metadata", "token_usage"):
            if isinstance(value.get(key), dict):
                return value[key]

        for child in value.values():
            result = find_usage(child)
            if result:
                return result

    elif isinstance(value, list):
        for child in value:
            result = find_usage(child)
            if result:
                return result

    return {}

# None이 아닌 첫번째 값 반환
def first_value(*values):
    return next((value for value in values if value is not None), None)

# Run 정보에 저장된 모델명 
def find_model(run):
    extra = getattr(run, "extra", {}) or {}
    metadata = extra.get("metadata", {}) or {}
    run_metadata = getattr(run, "metadata", {}) or {}
    invocation_params = extra.get("invocation_params", {}) or {}
    return first_value(getattr(run, "model", None), run_metadata.get("model_name"), metadata.get("model_name"), metadata.get("ls_model_name"), invocation_params.get("model"), invocation_params.get("model_name"), "")

# 상세 정보에 저장된 토큰값
def find_token_detail(usage, *names):
    value = first_value(*(usage.get(name) for name in names))
    if value is not None:
        return value

    for detail_key in ("input_tokens_details", "prompt_tokens_details", "prompt_token_details"):
        details = usage.get(detail_key) or {}
        if isinstance(details, dict):
            value = first_value(*(details.get(name) for name in names))
            if value is not None:
                return value
    return None

# ***************************************************
# * Trace 실행 시간 계산
# ***************************************************
def get_duration(run):
    if run.start_time and run.end_time:
        return (run.end_time - run.start_time).total_seconds()
    return first_value(
        getattr(run, "latency_seconds", None),
        getattr(run, "latency", None),
    )

# ***************************************************
# * Trace 데이터 구성
# ***************************************************
def extract_run_data(run, project_name=""):
    usage = find_usage(run.outputs or {})
    cost_details = usage.get("cost_details") or {}

    # LangSmith Run 최상위 필드를 우선 사용, 없으면 outputs 내부 값 fallback
    input_tokens = first_value(getattr(run, "prompt_tokens", None), getattr(run, "input_tokens", None), usage.get("input_tokens"), usage.get("prompt_tokens"))
    output_tokens = first_value(getattr(run, "completion_tokens", None), getattr(run, "output_tokens", None), usage.get("output_tokens"), usage.get("completion_tokens"))
    total_tokens = first_value(getattr(run, "total_tokens", None), usage.get("total_tokens"))

    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens

    prompt_token_details = getattr(run, "prompt_token_details", {}) or {}
    if not isinstance(prompt_token_details, dict):
        prompt_token_details = getattr(prompt_token_details, "raw", {}) or {}
    cached_input_tokens = first_value(
        getattr(run, "cached_tokens", None),
        prompt_token_details.get("cached_tokens"),
        prompt_token_details.get("cache_read_input_tokens"),
        find_token_detail(usage, "cached_tokens", "cache_read_tokens", "cache_read_input_tokens"),
    )
    cache_write_tokens = first_value(
        getattr(run, "cache_write_tokens", None),
        prompt_token_details.get("cache_write_tokens"),
        prompt_token_details.get("cache_creation_input_tokens"),
        find_token_detail(usage, "cache_write_tokens", "cache_creation_tokens", "cache_creation_input_tokens"),
    )

    total_cost = first_value(getattr(run, "total_cost", None), usage.get("total_cost"))
    input_cost = first_value(getattr(run, "prompt_cost", None), usage.get("input_cost"), usage.get("prompt_cost"), cost_details.get("upstream_inference_input_cost"))
    output_cost = first_value(getattr(run, "completion_cost", None), usage.get("output_cost"), usage.get("completion_cost"), cost_details.get("upstream_inference_output_cost"))

    return {
        "start_time": run.start_time.isoformat() if run.start_time else "",
        "run_id": run.id,
        "project_name": project_name,
        "model": find_model(run),
        "status": "error" if getattr(run, "error", None) else "success",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_input_tokens": cached_input_tokens,
        "cache_write_tokens": cache_write_tokens,
        "total_tokens": total_tokens,
        "total_cost": total_cost,
        "input_cost": input_cost,
        "output_cost": output_cost,
        "duration_seconds": get_duration(run),
    }

# ***************************************************
# * CSV 저장
# ***************************************************
def save_csv(rows, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

# ***************************************************
# * LangSmith Trace 조회
# ***************************************************
async def query_runs(client, project_id, min_start_time):
    selected_fields = [
        "ID",
        "NAME",
        "STATUS",
        "START_TIME",
        "END_TIME",
        "ERROR",
        "EXTRA",
        "METADATA",
        "OUTPUTS",
        "TOTAL_TOKENS",
        "PROMPT_TOKENS",
        "COMPLETION_TOKENS",
        "TOTAL_COST",
        "PROMPT_COST",
        "COMPLETION_COST",
        "PROMPT_TOKEN_DETAILS",
        "COMPLETION_TOKEN_DETAILS",
    ]
    paginator = client.runs.query(
        project_ids=[str(project_id)],
        run_type="LLM",
        min_start_time=min_start_time,
        page_size=1000,
        selects=selected_fields,
    )
    return [run async for run in paginator]

def main():
    load_dotenv(BASE_DIR / ".env")

    parser = argparse.ArgumentParser(description="LangSmith LLM Trace 사용량 조회 및 CSV 저장")
    parser.add_argument("--project-name", default=os.getenv("LANGSMITH_PROJECT"), help="조회할 LangSmith 프로젝트명")
    parser.add_argument("--since-days", type=int, default=7, help="최근 며칠간의 Trace를 조회할지 지정 (기본값: 7)")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH, help="저장할 CSV 경로")
    args = parser.parse_args()

    client = Client()
    project = client.read_project(project_name=args.project_name)
    min_start_time = datetime.now(timezone.utc) - timedelta(days=args.since_days)
    
    # SmithDB query API
    runs = asyncio.run(query_runs(client, project.id, min_start_time))
    runs.sort(key=lambda run: run.start_time.timestamp() if run.start_time else 0)
    
    # 저장 데이터 구성
    rows = [extract_run_data(run, args.project_name) for run in runs]
    save_csv(rows, args.output)

    # 조회 결과 요약
    counted_runs = sum(row["total_tokens"] is not None for row in rows)
    total_tokens = sum(row["total_tokens"] or 0 for row in rows)

    print(f"CSV 저장 경로: {args.output}")
    print(f"Trace 건수: {len(runs)}")
    print(f"토큰 사용량 확인 건수: {counted_runs}")
    print(f"총 토큰 사용량: {total_tokens:,}")

if __name__ == "__main__":
    main()
