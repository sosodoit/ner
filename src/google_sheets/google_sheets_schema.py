# -*- coding: utf-8 -*-
"""Google Sheets 검수 행의 컬럼과 최소 검증 규칙."""

READ_ONLY_COLUMNS = (
    "run_folder", "provider", "model", "dataset_version", "press",
    "doc_id", "sentence_id", "review_id", "source_sentence", "target_span",
    "target_type", "review_status", "error_lv1", "error_lv2",
    "corrected_span", "reason",
)
HUMAN_COLUMNS = ("human_status", "human_final_span", "human_final_type", "human_reason")
ALL_COLUMNS = READ_ONLY_COLUMNS + HUMAN_COLUMNS
KEY_COLUMNS = ("dataset_version", "doc_id", "sentence_id", "review_id")
STATUS_VALUES = ("미검수", "수정완료", "수정불필요", "보류")


def key(row):
    return tuple(str(row.get(column, "")).strip() for column in KEY_COLUMNS)


def prepare(row):
    result = {column: row.get(column, "") for column in ALL_COLUMNS}
    result["human_status"] = result["human_status"] or "미검수"
    return result


def errors(row):
    result = [f"식별자 누락: {column}" for column in KEY_COLUMNS if not str(row.get(column, "")).strip()]
    status = row.get("human_status") or "미검수"
    if status not in STATUS_VALUES:
        result.append(f"허용되지 않은 상태: {status}")
    elif status == "수정완료":
        for column in ("human_final_span", "human_final_type"):
            if not str(row.get(column, "")).strip():
                result.append(f"{status}인데 {column} 누락")
    elif row.get("human_final_span") or row.get("human_final_type"):
        result.append(f"{status} 상태에는 최종 개체명·태그를 입력할 수 없음")
    return result
