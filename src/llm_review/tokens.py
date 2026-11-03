import argparse
import csv
from pathlib import Path

from dotenv import load_dotenv
from langsmith import Client


BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_PROJECT_NAME = "ner-poc-20261030"
DEFAULT_OUTPUT_PATH = BASE_DIR / "outputs" / "langsmith_usage.csv"


def _find_usage(value):
    """Find the first usage object nested in a LangSmith run output."""
    if isinstance(value, dict):
        usage = value.get("usage")
        if isinstance(usage, dict):
            return usage
        for child in value.values():
            found = _find_usage(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_usage(child)
            if found is not None:
                return found
    return None


def _duration_seconds(run):
    latency = getattr(run, "latency", None)
    if latency is not None:
        return latency
    if run.start_time and run.end_time:
        return (run.end_time - run.start_time).total_seconds()
    return None


def main():
    load_dotenv(BASE_DIR / ".env")

    """
    parser = argparse.ArgumentParser(
        description="LangSmith LLM trace usage 조회 및 CSV 저장"
    )
    parser.add_argument(
        "--project-name",
        default=DEFAULT_PROJECT_NAME,
        help=f"조회할 LangSmith 프로젝트명 (기본값: {DEFAULT_PROJECT_NAME})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"저장할 CSV 경로 (기본값: {DEFAULT_OUTPUT_PATH})",
    )
    parser.add_argument(
        "--descending",
        action="store_true",
        help="최신 trace부터 정렬",
    )
    """
    parser = argparse.ArgumentParser(
        description="Fetch LangSmith LLM trace usage and save it as CSV."
    )
    parser.add_argument(
        "--project-name",
        default=DEFAULT_PROJECT_NAME,
        help=f"LangSmith project name (default: {DEFAULT_PROJECT_NAME})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Output CSV path (default: {DEFAULT_OUTPUT_PATH})",
    )
    parser.add_argument(
        "--descending",
        action="store_true",
        help="Sort newest traces first",
    )
    args = parser.parse_args()

    client = Client()
    runs = list(
        client.list_runs(
            project_name=args.project_name,
            run_type="llm",
        )
    )

    runs.sort(
        key=lambda run: run.start_time.isoformat() if run.start_time else "",
        reverse=args.descending,
    )

    fields = [
        "start_time",
        "run_id",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cost",
        "input_cost",
        "output_cost",
        "duration_seconds",
    ]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    total_tokens = 0
    counted_runs = 0

    with args.output.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fields)
        writer.writeheader()

        for run in runs:
            output_usage = _find_usage(getattr(run, "outputs", None)) or {}
            cost_details = output_usage.get("cost_details", {})
            total = output_usage.get("total_tokens")
            input_cost = output_usage.get(
                "input_cost", cost_details.get("upstream_inference_input_cost")
            )
            output_cost = output_usage.get(
                "output_cost", cost_details.get("upstream_inference_output_cost")
            )
            if total is not None:
                total_tokens += total
                counted_runs += 1

            writer.writerow(
                {
                    "start_time": run.start_time.isoformat()
                    if run.start_time
                    else "",
                    "run_id": run.id,
                    "input_tokens": output_usage.get("input_tokens"),
                    "output_tokens": output_usage.get("output_tokens"),
                    "total_tokens": total,
                    "cost": output_usage.get("cost"),
                    "input_cost": input_cost,
                    "output_cost": output_cost,
                    "duration_seconds": _duration_seconds(run),
                }
            )

    print(f"CSV saved: {args.output}")
    print(f"Trace count: {len(runs)}")
    print(f"Usage available: {counted_runs}")
    print(f"Total tokens: {total_tokens}")


if __name__ == "__main__":
    main()
