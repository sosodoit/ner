# -*- coding: utf-8 -*-
"""BigQuery 결과를 Google Sheets에 생성·갱신한다."""

import argparse
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import bigquery
from google.oauth2 import service_account
from googleapiclient.discovery import build

from google_sheets_schema import ALL_COLUMNS, HUMAN_COLUMNS, key, prepare, errors

BASE_DIR = Path(__file__).resolve().parent
FOLDER_ID = "1k4Bj3Vy20TZDdVIN2bUKHTbZsptaXQlh"
SPREADSHEET_ID = "1O9BzNmx8aj_ZGxFTdglssI4Sfd1WeKRUpowEDWsZFrQ"
SCOPES = ("https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(BASE_DIR / "export_google_sheet.log", encoding="utf-8"), logging.StreamHandler()],
)


def source_sentences(version, press):
    path = BASE_DIR / "data" / version / f"{press}.json"
    if not path.is_file():
        raise FileNotFoundError(f"원본 JSON 없음: {path}")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return {
        (document["id"], sentence["id"]): sentence.get("form", "")
        for document in data.get("document", [])
        for paragraph in document.get("paragraph", [])
        for sentence in paragraph.get("sentence", [])
    }


def query_rows(client, table_id, run_folder):
    query = f"SELECT * FROM `{table_id}` WHERE run_folder = @run_folder"
    config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("run_folder", "STRING", run_folder)]
    )
    return [dict(row) for row in client.query(query, job_config=config).result()]


def index_rows(rows):
    indexed, problems = {}, []
    for row in rows:
        row_key = key(row)
        if row_key in indexed:
            problems.append(f"휴먼 입력 중복 키: {row_key}")
        else:
            indexed[row_key] = row
    return indexed, problems


def make_rows(results, source, old_rows):
    old, problems = index_rows(old_rows)
    output, seen = [], set()
    for result in results:
        row = prepare(result)
        row_key = key(row)
        if row_key in seen:
            problems.append(f"BigQuery 결과 중복 키: {row_key}")
            continue
        seen.add(row_key)

        original = source.get((row["press"], row["doc_id"], row["sentence_id"]))
        if original is None:
            problems.append(f"원문 연결 실패: {row_key}")
            continue
        if row["source_sentence"] and row["source_sentence"] != original:
            problems.append(f"원문 불일치: {row_key}")
            continue
        row["source_sentence"] = original
        if row_key in old:
            row.update({column: old[row_key].get(column, "") for column in HUMAN_COLUMNS})
        row_errors = errors(row)
        problems.extend(f"{row_key}: {problem}" for problem in row_errors)
        if not row_errors:
            output.append({column: row.get(column, "") for column in ALL_COLUMNS})

    output.sort(key=lambda row: (row["review_status"] != "error", key(row)))
    return output, problems


def google_services():
    path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_DB")
    if not path:
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS_DB가 설정되지 않음")
    path = Path(path)
    credentials = service_account.Credentials.from_service_account_file(
        str(path if path.is_absolute() else BASE_DIR / path), scopes=SCOPES
    )
    return (
        build("drive", "v3", credentials=credentials, cache_discovery=False),
        build("sheets", "v4", credentials=credentials, cache_discovery=False),
    )


def get_sheet_id(drive, folder_id, name):
    query = f"'{folder_id}' in parents and name = '{name}' and trashed = false"
    files = drive.files().list(q=query, fields="files(id)").execute().get("files", [])
    if files:
        return files[0]["id"]
    return drive.files().create(body={
        "name": name, "mimeType": "application/vnd.google-apps.spreadsheet", "parents": [folder_id]
    }, fields="id").execute()["id"]


def first_sheet(sheets, sheet_id):
    info = sheets.spreadsheets().get(
        spreadsheetId=sheet_id, fields="sheets(properties(sheetId,title))"
    ).execute()
    return info["sheets"][0]["properties"]


def sheet_rows(sheets, sheet_id):
    sheet = first_sheet(sheets, sheet_id)
    values = sheets.spreadsheets().values().get(
        spreadsheetId=sheet_id, range=f"'{sheet['title']}'!A:Z"
    ).execute().get("values", [])
    return [dict(zip(values[0], row)) for row in values[1:]] if len(values) > 1 else []


def write_sheet(sheets, sheet_id, rows):
    sheet = first_sheet(sheets, sheet_id)
    values = [list(ALL_COLUMNS)] + [[row.get(column, "") for column in ALL_COLUMNS] for row in rows]
    range_name = f"'{sheet['title']}'!A:Z"
    sheets.spreadsheets().values().clear(spreadsheetId=sheet_id, range=range_name, body={}).execute()
    sheets.spreadsheets().values().update(
        spreadsheetId=sheet_id, range=f"'{sheet['title']}'!A1", valueInputOption="RAW", body={"values": values}
    ).execute()
    status_column = ALL_COLUMNS.index("human_status")
    sheets.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": [
        {"updateSheetProperties": {"properties": {"sheetId": sheet["sheetId"], "gridProperties": {"frozenRowCount": 1}}, "fields": "gridProperties.frozenRowCount"}},
        {"setBasicFilter": {"filter": {"range": {"sheetId": sheet["sheetId"], "startRowIndex": 0, "endRowIndex": len(values), "endColumnIndex": len(ALL_COLUMNS)}}}},
        {"setDataValidation": {"range": {
            "sheetId": sheet["sheetId"], "startRowIndex": 1, "endRowIndex": max(1, len(values)),
            "startColumnIndex": status_column, "endColumnIndex": status_column + 1,
        }, "rule": {
            "condition": {"type": "ONE_OF_LIST", "values": [
                {"userEnteredValue": value} for value in ("미검수", "수정완료", "수정불필요", "보류")
            ]},
            "strict": True, "showCustomUi": True,
        }}}
    ]}).execute()


def main():
    load_dotenv(BASE_DIR / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("run_folder")
    parser.add_argument("--sheet-name")
    parser.add_argument(
        "--spreadsheet-id",
        default=os.getenv("GOOGLE_SPREADSHEET_ID") or SPREADSHEET_ID,
        help="미리 만든 Google Sheet ID",
    )
    parser.add_argument("--drive-folder-id", default=os.getenv("GOOGLE_DRIVE_FOLDER_ID", FOLDER_ID))
    args = parser.parse_args()

    table_id = ".".join(os.getenv(name, "") for name in ("GCP_PROJECT_ID", "GCP_DATASET_ID", "GCP_TABLE_NAME"))
    results = query_rows(bigquery.Client(), table_id, args.run_folder)
    if not results:
        raise RuntimeError(f"BigQuery 결과 없음: {args.run_folder}")

    version = results[0].get("dataset_version") or args.run_folder.split("/", 1)[0]
    source = {}
    for press in {row.get("press") for row in results}:
        source.update({(press, *item_key): value for item_key, value in source_sentences(version, press).items()})

    drive, sheets = google_services()
    name = args.sheet_name or f"NER_검수_{args.run_folder.replace('/', '_')}"
    sheet_id = args.spreadsheet_id or get_sheet_id(drive, args.drive_folder_id, name)
    rows, problems = make_rows(results, source, sheet_rows(sheets, sheet_id))
    if problems:
        error_path = BASE_DIR / "outputs" / args.run_folder / "google_sheet.errors.json"
        error_path.parent.mkdir(parents=True, exist_ok=True)
        error_path.write_text(json.dumps(problems, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        logging.error(f"오류 {len(problems)}건으로 갱신 중단: {error_path}")
        return 1

    write_sheet(sheets, sheet_id, rows)
    logging.info(f"Google Sheets 갱신완료: https://docs.google.com/spreadsheets/d/{sheet_id}/edit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
