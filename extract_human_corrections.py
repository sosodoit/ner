# -*- coding: utf-8 -*-
"""Google Sheets에서 휴먼 확정 수정 내역만 추출한다."""

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from export_google_sheet import BASE_DIR, SPREADSHEET_ID, first_sheet, google_services
from google_sheets_schema import key


def read_rows(sheets, spreadsheet_id):
    sheet = first_sheet(sheets, spreadsheet_id)
    values = sheets.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet['title']}'!A:Z",
    ).execute().get("values", [])
    return [dict(zip(values[0], row)) for row in values[1:]] if len(values) > 1 else []


def extract(rows):
    corrections = []
    errors = []
    seen = set()
    for row_number, row in enumerate(rows, 2):
        if row.get("human_status") != "수정완료":
            continue

        row_key = key(row)
        if row_key in seen:
            errors.append(f"행 {row_number}: 안정 키 중복 - {row_key}")
            continue
        seen.add(row_key)

        missing = [
            column for column in ("dataset_version", "doc_id", "sentence_id", "review_id", "human_final_span", "human_final_type")
            if not str(row.get(column, "")).strip()
        ]
        if missing:
            errors.append(f"행 {row_number}: 필수값 누락 - {', '.join(missing)}")
            continue

        corrections.append({
            "dataset_version": row.get("dataset_version", ""),
            "doc_id": row["doc_id"],
            "sentence_id": row["sentence_id"],
            "review_id": row["review_id"],
            "target_span": row.get("target_span", ""),
            "human_final_span": row["human_final_span"],
            "human_final_type": row["human_final_type"],
            "human_reason": row.get("human_reason", ""),
        })
    return corrections, errors


def main():
    load_dotenv(BASE_DIR / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("--spreadsheet-id", default=os.getenv("GOOGLE_SPREADSHEET_ID") or SPREADSHEET_ID)
    parser.add_argument("--output", type=Path, default=BASE_DIR / "outputs" / "human_corrections.json")
    args = parser.parse_args()

    _, sheets = google_services()
    corrections, errors = extract(read_rows(sheets, args.spreadsheet_id))
    if errors:
        error_path = args.output.with_suffix(".errors.json")
        error_path.parent.mkdir(parents=True, exist_ok=True)
        error_path.write_text(json.dumps(errors, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"추출 중단: 오류 {len(errors)}건 - {error_path}")
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(corrections, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"추출 완료: {len(corrections)}건 - {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
