# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: ner_documents 적재
# * 설명:
# * - 테이블 생성 후 적재
# * - python -m src.postgresql.insert.ner_documents data/test/test_data_v2/강원일보.json --create-table
# * - 기존 테이블 삭제 후 재생성
# * - python -m src.postgresql.insert.ner_documents data/test/test_data_v2/강원일보.json --reset-table
# * - 데이터만 적재
# * - python -m src.postgresql.insert.ner_documents data/test/test_data_v2/강원일보.json
# ***************************************************
import json
import argparse
from pathlib import Path
from psycopg.types.json import Jsonb
from src.config import get_postgre_connect

BASE_DIR = Path(__file__).resolve().parents[3]
SCHEMA_PATH = BASE_DIR / "src/postgresql/schema/ner_documents.sql"

# 테이블 생성
def create_table():
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with get_postgre_connect() as connection:
        connection.execute(schema_sql)
    print("ner_documents 테이블 생성 완료")

# 테이블 삭제
def drop_table():
    with get_postgre_connect() as connection:
        connection.execute("DROP TABLE IF EXISTS ner_documents")
    print("ner_documents 테이블 삭제 완료")

# 정보 추출
def make_document_rows(input_path):
    input_data = json.loads(Path(input_path).read_text(encoding="utf-8-sig"))
    corpus_metadata = Jsonb(input_data.get("metadata"))
    rows = []

    for document_order, document in enumerate(input_data["document"], start=1):
        document_metadata = document.get("metadata", {})

        for paragraph_order, paragraph in enumerate(document["paragraph"], start=1):
            for sentence_order, sentence in enumerate(paragraph["sentence"], start=1):
                rows.append(
                    (
                        document["id"],
                        document_order,
                        paragraph["id"],
                        sentence["id"],
                        corpus_metadata,
                        document_metadata.get("title"),
                        document_metadata.get("author"),
                        document_metadata.get("publisher"),
                        document_metadata.get("date"),
                        document_metadata.get("topic"),
                        document_metadata.get("original_topic"),
                        sentence["form"],
                        paragraph_order,
                        sentence_order,
                    )
                )

    return rows

# 적재
def insert_ner_documents(input_path):
    rows = make_document_rows(input_path)
    if not rows:
        return 0

    insert_sql = """
        INSERT INTO ner_documents (
            doc_id,
            document_order,
            paragraph_id,
            sentence_id,
            corpus_metadata,
            document_title,
            author,
            publisher,
            date,
            topic,
            original_topic,
            form,
            paragraph_order,
            sentence_order
        )
        VALUES (
            %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s
        )
        ON CONFLICT (doc_id, sentence_id) DO UPDATE SET
            document_order = EXCLUDED.document_order,
            paragraph_id = EXCLUDED.paragraph_id,
            corpus_metadata = EXCLUDED.corpus_metadata,
            document_title = EXCLUDED.document_title,
            author = EXCLUDED.author,
            publisher = EXCLUDED.publisher,
            date = EXCLUDED.date,
            topic = EXCLUDED.topic,
            original_topic = EXCLUDED.original_topic,
            form = EXCLUDED.form,
            paragraph_order = EXCLUDED.paragraph_order,
            sentence_order = EXCLUDED.sentence_order
    """

    with get_postgre_connect() as connection:
        with connection.cursor() as cursor:
            cursor.executemany(insert_sql, rows)

    return len(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_path")
    parser.add_argument("--create-table", action="store_true", help="테이블 생성")
    parser.add_argument("--reset-table", action="store_true", help="기존 테이블 삭제 후 재생성")
    args = parser.parse_args()

    if args.create_table and args.reset_table:
        parser.error("--create-table과 --reset-table은 동시에 사용할 수 없습니다.")

    if args.reset_table:
        drop_table()
        create_table()

    elif args.create_table:
        create_table()

    row_count = insert_ner_documents(args.input_path)
    print(f"ner_documents 적재 완료: {row_count}건")


if __name__ == "__main__":
    main()