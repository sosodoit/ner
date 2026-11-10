# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: ner_rule_results 적재
# * 설명:
# * - 테이블 생성 후 적재
# * - python -m src.postgresql.insert.ner_rule_results data/filter/rule_detect_data/20261110_175720 --create-table
# * - 기존 테이블 삭제 후 재생성
# * - python -m src.postgresql.insert.ner_rule_results data/filter/rule_detect_data/20261110_175720 --reset-table
# * - 데이터만 적재
# * - python -m src.postgresql.insert.ner_rule_results data/filter/rule_detect_data/20261110_175720
# ***************************************************
import argparse
import pandas as pd
from pathlib import Path
from psycopg.types.json import Jsonb
from src.config import get_postgre_connect

BASE_DIR = Path(__file__).resolve().parents[3]
SCHEMA_PATH = BASE_DIR / "src/postgresql/schema/ner_rule_results.sql"

# 테이블 생성 
def create_table():
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with get_postgre_connect() as connection:
        connection.execute(schema_sql)
    print("ner_rule_results 테이블 생성 완료")

# 테이블 삭제
def drop_table():
    with get_postgre_connect() as connection:
        connection.execute("DROP TABLE IF EXISTS ner_rule_results")
    print("ner_rule_results 테이블 삭제 완료")

# 정보 추출
def _json_value(value):
    if pd.isna(value):
        return None
    if isinstance(value, bool):
        return value
    return str(value)

def _make_rule_results(row, rule_columns):
    return {
        rule: {
            "detected": bool(row[rule]),
            "pattern": _json_value(row.get(f"{rule}_PATTERN")),
        }
        for rule in rule_columns
    }

def make_rule_result_rows(input_dir):
    input_dir = Path(input_dir)
    run_id = input_dir.name
    rows = []
    rule_files = sorted(input_dir.glob("*.pkl"))

    for rule_file in rule_files:
        rule_data = pd.read_pickle(rule_file)
        rule_columns = sorted(
            column
            for column in rule_data.columns
            if column.startswith(("EXT_S", "EXT_E"))
            and not column.endswith("_PATTERN")
        )
        sentence_rules = [column for column in rule_columns if "_S" in column]
        entity_rules = [column for column in rule_columns if "_E" in column]

        for _, row in rule_data.drop_duplicates(subset=["doc_id", "sentence_id"]).iterrows():
            rows.append(
                (
                    run_id,
                    row["doc_id"],
                    row["sentence_id"],
                    None,
                    "sentence",
                    Jsonb(_make_rule_results(row, sentence_rules)),
                )
            )

        for _, row in rule_data.loc[rule_data["entity_id"].notna()].iterrows():
            rows.append(
                (
                    run_id,
                    row["doc_id"],
                    row["sentence_id"],
                    row["entity_id"],
                    "entity",
                    Jsonb(_make_rule_results(row, entity_rules)),
                )
            )

    return rows


def insert_ner_rule_results(input_dir):
    rows = make_rule_result_rows(input_dir)
    if not rows:
        return 0

    insert_sql = """
        INSERT INTO ner_rule_results (
            run_id,
            doc_id,
            sentence_id,
            entity_id,
            rule_unit,
            rule_results
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (run_id, doc_id, sentence_id, entity_id) DO UPDATE SET
            rule_unit = EXCLUDED.rule_unit,
            rule_results = EXCLUDED.rule_results
    """

    with get_postgre_connect() as connection:
        with connection.cursor() as cursor:
            cursor.executemany(insert_sql, rows)

    return len(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir")
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

    row_count = insert_ner_rule_results(args.input_dir)
    print(f"ner_rule_results 적재 완료: {row_count}건")


if __name__ == "__main__":
    main()
