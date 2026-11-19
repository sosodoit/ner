# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: ner_human_review 초기 적재
# * 설명: ner_rule_results_3를 기준으로 문장 단위 검수 관리행을 생성
# ***************************************************
import argparse
from pathlib import Path

import pandas as pd

from src.config import get_postgre_connect


BASE_DIR = Path(__file__).resolve().parents[3]
SCHEMA_PATH = BASE_DIR / "src/postgresql/schema/ner_human_review.sql"
MARTIAL_LAW_RESULTS_DIR = BASE_DIR / "data/filter/rule_detect_data/all_pass_ner_tagged_5_martial_law"


def create_table():
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with get_postgre_connect() as connection:
        connection.execute(schema_sql)
    print("ner_human_review 테이블 생성 완료")


def drop_table():
    with get_postgre_connect() as connection:
        connection.execute("DROP TABLE IF EXISTS ner_human_review")
    print("ner_human_review 테이블 삭제 완료")


def _load_martial_law_rows(data_version):
    rows = []
    if not MARTIAL_LAW_RESULTS_DIR.is_dir():
        return rows

    for rule_file in sorted(MARTIAL_LAW_RESULTS_DIR.glob("*.csv")):
        rule_data = pd.read_csv(rule_file, encoding="utf-8-sig")
        required_columns = {"doc_id", "sentence_id", "form", "EXT_S001"}
        if not required_columns.issubset(rule_data.columns):
            continue

        emergency_doc_ids = set(rule_data.loc[rule_data["EXT_S001"].fillna(False), "doc_id"].dropna())
        emergency_data = rule_data[rule_data["doc_id"].isin(emergency_doc_ids)]
        emergency_data = emergency_data.drop_duplicates(subset=["doc_id", "sentence_id"])

        rows.extend(
            (
                data_version,
                rule_file.stem,
                row.doc_id,
                row.sentence_id,
                None if pd.isna(row.form) else row.form,
                None if pd.isna(row.form) else row.form,
                "휴먼검수",
                "미완료",
                False,
                None,
                None,
            )
            for row in emergency_data.itertuples(index=False)
        )

    return rows


def insert_ner_human_review(data_version=None):
    version_filter = "AND r.data_version = %s" if data_version else ""
    query = f"""
        INSERT INTO ner_human_review (
            data_version, press, doc_id, sentence_id, original_form,
            modified_form, review_method, review_status, is_modified,
            assignee, updated_at
        )
        SELECT DISTINCT
            r.data_version,
            regexp_replace(r.data_version, '^.*_', '') AS press,
            r.doc_id,
            r.sentence_id,
            r.form AS original_form,
            r.form AS modified_form,
            CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM ner_rule_results_3 emergency
                    WHERE emergency.data_version = r.data_version
                      AND emergency.doc_id = r.doc_id
                      AND emergency.form ILIKE '%%계엄%%'
                ) THEN '휴먼검수'
                WHEN EXISTS (
                    SELECT 1
                    FROM jsonb_each_text(to_jsonb(r)) AS rule(key, value)
                    WHERE rule.key LIKE 'EXT_E003_%%'
                      AND rule.key NOT LIKE '%%_PATTERN'
                      AND rule.value = 'true'
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM jsonb_each_text(to_jsonb(r)) AS rule(key, value)
                    WHERE rule.key LIKE 'EXT_%%'
                      AND rule.key NOT LIKE '%%_PATTERN'
                      AND rule.key NOT LIKE 'EXT_E003_%%'
                      AND rule.value = 'true'
                ) THEN '일괄처리'
                ELSE 'LLM검수'
            END AS review_method,
            '미완료' AS review_status,
            FALSE AS is_modified,
            NULL::TEXT AS assignee,
            NULL::TIMESTAMPTZ AS updated_at
        FROM ner_rule_results_3 r
        WHERE 1 = 1
          {version_filter}
        ON CONFLICT (data_version, press, doc_id, sentence_id) DO NOTHING
    """

    parameters = (data_version,) if data_version else ()
    legacy_versions = [data_version] if data_version else None
    legacy_rows = []

    with get_postgre_connect() as connection:
        if legacy_versions is None:
            version_rows = connection.execute(
                "SELECT DISTINCT data_version FROM ner_rule_results_3"
            ).fetchall()
            legacy_versions = [row[0] for row in version_rows]

        with connection.cursor() as cursor:
            cursor.execute(query, parameters)
            row_count = cursor.rowcount

            for legacy_version in legacy_versions:
                legacy_rows.extend(_load_martial_law_rows(legacy_version))

            if legacy_rows:
                cursor.executemany(
                    """
                    INSERT INTO ner_human_review (
                        data_version, press, doc_id, sentence_id, original_form,
                        modified_form, review_method, review_status, is_modified,
                        assignee, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (data_version, press, doc_id, sentence_id)
                    DO NOTHING
                    """,
                    legacy_rows,
                )
                row_count += cursor.rowcount

    print(f"ner_human_review 초기 적재 완료: {row_count}건")
    return row_count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-version")
    parser.add_argument("--create-table", action="store_true")
    parser.add_argument("--reset-table", action="store_true")
    args = parser.parse_args()

    if args.create_table and args.reset_table:
        parser.error("--create-table과 --reset-table은 동시에 사용할 수 없습니다.")

    if args.reset_table:
        drop_table()
        create_table()
    elif args.create_table:
        create_table()

    insert_ner_human_review(data_version=args.data_version)


if __name__ == "__main__":
    main()
