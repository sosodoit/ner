# -*- coding: utf-8 -*-
"""적재된 후처리 언론사별 CSV를 ner_rule_results_3에 적재한다."""
import argparse
from pathlib import Path

import pandas as pd
from psycopg import sql

from src.config import get_postgre_connect


BASE_DIR = Path(__file__).resolve().parents[3]
SCHEMA_PATH = BASE_DIR / "src/postgresql/schema/ner_rule_results_3.sql"


def create_table():
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with get_postgre_connect() as connection:
        connection.execute(schema_sql)
    print("ner_rule_results_3 테이블 생성 완료")


def drop_table():
    with get_postgre_connect() as connection:
        connection.execute("DROP TABLE IF EXISTS ner_rule_results_3")
    print("ner_rule_results_3 테이블 삭제 완료")


def _is_detected(value):
    if pd.isna(value):
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "y", "yes"}


def _normalise_column(column):
    # 후처리 CSV의 EXT_E005 컬럼명에는 공백 처리
    if column.startswith("EXT_E005_"):
        return column.replace(" ", "")
    return column


def _to_db_value(column, value):
    if pd.isna(value):
        return None
    if column.startswith(("EXT_S", "EXT_E")) and not column.endswith("_PATTERN"):
        return _is_detected(value)
    return str(value)


def _make_insert_sql(columns):
    insert_columns = ["data_version", *columns]
    column_sql = sql.SQL(", ").join(sql.Identifier(column) for column in insert_columns)
    placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in insert_columns)
    update_columns = [
        column
        for column in columns
        if column not in {"doc_id", "sentence_id", "entity_id"}
    ]
    update_sql = sql.SQL(", ").join(
        sql.SQL("{column} = EXCLUDED.{column}").format(column=sql.Identifier(column))
        for column in update_columns
    )
    return sql.SQL("""
        INSERT INTO ner_rule_results_3 ({columns})
        VALUES ({values})
        ON CONFLICT (data_version, doc_id, sentence_id, entity_id) DO UPDATE SET
            {updates}
    """).format(
        columns=column_sql,
        values=placeholders,
        updates=update_sql,
    )


def _make_chunk_rows(rule_data, columns, data_version):
    return [
        tuple(
            [data_version]
            + [_to_db_value(column, value) for column, value in zip(columns, row)]
        )
        for row in rule_data.itertuples(index=False, name=None)
    ]


def insert_ner_rule_results_3(input_csv, data_version, chunk_size=1000):
    input_csv = Path(input_csv)
    if not data_version:
        raise ValueError("data_version 인자가 필요합니다.")
    if chunk_size <= 0:
        raise ValueError("chunk_size는 1 이상이어야 합니다.")
    if not input_csv.is_file():
        raise FileNotFoundError(f"언론사별 후처리 CSV가 없습니다: {input_csv}")

    source_columns = list(
        pd.read_csv(input_csv, encoding="utf-8-sig", nrows=0).columns
    )
    columns = [_normalise_column(column) for column in source_columns]
    insert_sql = _make_insert_sql(columns)
    total = 0

    with get_postgre_connect() as connection:
        with connection.cursor() as cursor:
            for rule_data in pd.read_csv(
                input_csv,
                encoding="utf-8-sig",
                chunksize=chunk_size,
            ):
                rule_data.columns = columns
                rows = _make_chunk_rows(rule_data, columns, data_version)
                if rows:
                    cursor.executemany(insert_sql, rows)
                    total += len(rows)

    print(f"{input_csv.name}: {total}건 처리")

    print(f"ner_rule_results_3 적재 누계: {total}건")
    return total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_csv")
    parser.add_argument("--data-version", required=True)
    parser.add_argument("--create-table", action="store_true")
    parser.add_argument("--reset-table", action="store_true")
    parser.add_argument("--chunk-size", type=int, default=1000)
    args = parser.parse_args()

    if args.create_table and args.reset_table:
        parser.error("--create-table과 --reset-table은 동시에 사용할 수 없습니다.")

    if args.reset_table:
        drop_table()
        create_table()
    elif args.create_table:
        create_table()

    row_count = insert_ner_rule_results_3(
        args.input_csv,
        data_version=args.data_version,
        chunk_size=args.chunk_size,
    )
    print(f"ner_rule_results_3 적재 완료: {row_count}건")


if __name__ == "__main__":
    main()
