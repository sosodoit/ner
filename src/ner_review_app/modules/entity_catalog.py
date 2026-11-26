"""완료된 수정 문장을 반영해 기사 단위로 개체명 목록을 갱신한다."""

import os

from psycopg import sql

from src.ner_review_app.modules.postgredb import get_postgre_connect


INDEX_STATEMENTS = (
    "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS idx_entity_frequency_name_type "
    "ON public.ner_entity_frequency (entity_name, entity_type)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_entity_frequency_count "
    "ON public.ner_entity_frequency (mention_count DESC, entity_name DESC, entity_type DESC)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_entity_location_entity "
    "ON public.ner_entity_location (entity_name, entity_type, doc_id, sentence_id)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_entity_location_doc "
    "ON public.ner_entity_location (doc_id)",
)
REQUIRED_INDEXES = {
    "idx_entity_frequency_name_type",
    "idx_entity_frequency_count",
    "idx_entity_location_entity",
    "idx_entity_location_doc",
}

# 화면의 기사별 재집계와 노트북의 목록 추출·배치 적재에서 같은 최종 문장을 사용한다.
ENTITY_SOURCE_CTE_SQL = r"""
    WITH source AS (
        SELECT COALESCE(d.publisher, split_part(d.doc_id, '.', 1)) AS press_id,
               split_part(d.doc_id, '.', 1) AS file_id,
               d.doc_id, d.paragraph_id, d.sentence_id, d.topic, d.form,
               COALESCE(r.modified_form, d.form) AS final_form
        FROM public.ner_documents d
        LEFT JOIN LATERAL (
            SELECT modified_form FROM (
                SELECT h.modified_form, h.updated_at, h.data_version, 0 AS source_priority
                FROM public.ner_human_review h
                WHERE h.press = d.publisher AND h.doc_id = d.doc_id
                  AND h.sentence_id = d.sentence_id
                  AND h.review_status = '완료' AND h.is_modified
                  AND h.modified_form IS NOT NULL
                UNION ALL
                SELECT a.modified_form, a.updated_at, a.data_version, 1 AS source_priority
                FROM public.ner_human_review_add a
                WHERE a.press = d.publisher AND a.doc_id = d.doc_id
                  AND a.sentence_id = d.sentence_id
                  AND a.review_status = '완료' AND a.is_modified
                  AND a.modified_form IS NOT NULL
            ) completed
            -- 수정 시각과 버전까지 같으면 참고 문장의 추가 검수 결과를 우선한다.
            ORDER BY updated_at DESC NULLS LAST, data_version DESC, source_priority DESC
            LIMIT 1
        ) r ON TRUE
        WHERE d.doc_id = ANY(%s)
    )
"""
ENTITY_MENTIONS_INSERT_SQL = ENTITY_SOURCE_CTE_SQL + r"""
    INSERT INTO public.ner_entity_mentions
        (press_id, file_id, doc_id, paragraph_id, sentence_id,
         topic, form, final_form, entity_name, entity_type)
    SELECT s.press_id, s.file_id, s.doc_id, s.paragraph_id,
           s.sentence_id, s.topic, s.form, s.final_form, m[1], m[2]
    FROM source s
    CROSS JOIN LATERAL regexp_matches(
        s.final_form, '<\s*([^<>:]+?)\s*:\s*([^<>]+?)\s*>', 'g'
    ) m
"""


def check_admin_password(password):
    expected = os.getenv("NER_ASSIGNMENT_PASSWORD", "")
    return bool(expected) and password == expected


def catalog_ready():
    with get_postgre_connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            rows = cursor.execute(
                """
                SELECT index_class.relname AS indexname
                FROM pg_index index_info
                JOIN pg_class index_class ON index_class.oid = index_info.indexrelid
                JOIN pg_namespace index_schema ON index_schema.oid = index_class.relnamespace
                WHERE index_schema.nspname = 'public' AND index_info.indisvalid
                  AND index_class.relname = ANY(%s)
                """,
                (list(REQUIRED_INDEXES),),
            ).fetchall()
            log_exists = cursor.execute(
                "SELECT to_regclass('public.ner_entity_refresh_log') IS NOT NULL AS exists"
            ).fetchone()["exists"]
    return log_exists and REQUIRED_INDEXES <= {row["indexname"] for row in rows}


def prepare_catalog(password):
    if not check_admin_password(password):
        raise ValueError("관리 비밀번호가 올바르지 않습니다.")
    with get_postgre_connect() as conn:
        conn.autocommit = True
        invalid_indexes = conn.execute(
            """
            SELECT index_class.relname AS indexname
            FROM pg_index index_info
            JOIN pg_class index_class ON index_class.oid = index_info.indexrelid
            JOIN pg_namespace index_schema ON index_schema.oid = index_class.relnamespace
            WHERE index_schema.nspname = 'public' AND NOT index_info.indisvalid
              AND index_class.relname = ANY(%s)
            """,
            (list(REQUIRED_INDEXES),),
        ).fetchall()
        for row in invalid_indexes:
            conn.execute(
                sql.SQL("DROP INDEX CONCURRENTLY IF EXISTS {}").format(
                    sql.Identifier("public", row["indexname"])
                )
            )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS public.ner_entity_refresh_log (
                doc_id TEXT PRIMARY KEY,
                refreshed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        for statement in INDEX_STATEMENTS:
            conn.execute(statement)


def entity_search_pattern(value):
    """LIKE의 특수문자도 검색어 자체로 취급한다."""
    value = value.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{value}%"


def load_catalog_page(after=None, search_text="", limit=50):
    conditions = []
    params = []
    if search_text.strip():
        conditions.append("(entity_name ILIKE %s OR entity_type ILIKE %s)")
        params.extend([entity_search_pattern(search_text)] * 2)
    if after is not None:
        conditions.append("(mention_count, entity_name, entity_type) < (%s, %s, %s)")
        params.extend(after)
    params.append(limit)
    with get_postgre_connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '15s'")
            return cursor.execute(
                f"""
                SELECT entity_name, entity_type, mention_count
                FROM public.ner_entity_frequency
                WHERE {" AND ".join(conditions) or "TRUE"}
                ORDER BY mention_count DESC, entity_name DESC, entity_type DESC
                LIMIT %s
                """,
                params,
            ).fetchall()


def load_locations(entity_name, entity_type, after=None, limit=50):
    with get_postgre_connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            where = "" if after is None else "AND (doc_id, sentence_id) > (%s, %s)"
            params = (entity_name, entity_type, limit) if after is None else (entity_name, entity_type, *after, limit)
            return cursor.execute(
                f"""
                SELECT press_id, file_id, doc_id, paragraph_id, sentence_id, mention_count
                FROM public.ner_entity_location
                WHERE entity_name = %s AND entity_type = %s {where}
                ORDER BY doc_id, sentence_id
                LIMIT %s
                """,
                params,
            ).fetchall()


def load_pending_articles(press, limit=100):
    with get_postgre_connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            return cursor.execute(
                """
                WITH changed AS (
                    SELECT doc_id, MAX(updated_at) AS changed_at
                    FROM (
                        SELECT doc_id, updated_at FROM public.ner_human_review
                        WHERE press = %s AND review_status = '완료'
                          AND is_modified AND updated_at IS NOT NULL
                        UNION ALL
                        SELECT doc_id, updated_at FROM public.ner_human_review_add
                        WHERE press = %s AND review_status = '완료'
                          AND is_modified AND updated_at IS NOT NULL
                    ) reviews
                    GROUP BY doc_id
                )
                SELECT c.doc_id, c.changed_at
                FROM changed c
                LEFT JOIN public.ner_entity_refresh_log l USING (doc_id)
                WHERE l.refreshed_at IS NULL OR l.refreshed_at < c.changed_at
                ORDER BY c.changed_at DESC, c.doc_id
                LIMIT %s
                """,
                (press, press, limit),
            ).fetchall()


def refresh_article(doc_id, password):
    if not check_admin_password(password):
        raise ValueError("관리 비밀번호가 올바르지 않습니다.")
    with get_postgre_connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (doc_id,))
            valid = cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM public.ner_human_review
                    WHERE doc_id = %s AND review_status = '완료' AND is_modified
                    UNION ALL
                    SELECT 1 FROM public.ner_human_review_add
                    WHERE doc_id = %s AND review_status = '완료' AND is_modified
                ) AS valid
                """,
                (doc_id, doc_id),
            ).fetchone()["valid"]
            if not valid:
                raise ValueError("수정완료된 검수 문장이 있는 기사만 재집계할 수 있습니다.")
            source_exists = cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM public.ner_documents WHERE doc_id = %s) AS exists",
                (doc_id,),
            ).fetchone()["exists"]
            if not source_exists:
                raise ValueError("원본 기사에 없는 기사 ID입니다.")

            old_rows = cursor.execute(
                """
                SELECT entity_name, entity_type, COUNT(*) AS mention_count
                FROM public.ner_entity_mentions WHERE doc_id = %s
                GROUP BY entity_name, entity_type
                """,
                (doc_id,),
            ).fetchall()
            cursor.execute("DELETE FROM public.ner_entity_mentions WHERE doc_id = %s", (doc_id,))
            cursor.execute(
                ENTITY_MENTIONS_INSERT_SQL,
                ([doc_id],),
            )
            new_rows = cursor.execute(
                """
                SELECT entity_name, entity_type, COUNT(*) AS mention_count
                FROM public.ner_entity_mentions WHERE doc_id = %s
                GROUP BY entity_name, entity_type
                """,
                (doc_id,),
            ).fetchall()
            old = {(row["entity_name"], row["entity_type"]): row["mention_count"] for row in old_rows}
            new = {(row["entity_name"], row["entity_type"]): row["mention_count"] for row in new_rows}
            for key in sorted(old.keys() | new.keys()):
                delta = new.get(key, 0) - old.get(key, 0)
                if delta > 0:
                    cursor.execute(
                        """
                        INSERT INTO public.ner_entity_frequency
                            (entity_name, entity_type, mention_count)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (entity_name, entity_type) DO UPDATE
                        SET mention_count = ner_entity_frequency.mention_count + EXCLUDED.mention_count
                        """,
                        (*key, delta),
                    )
                elif delta < 0:
                    cursor.execute(
                        """
                        UPDATE public.ner_entity_frequency
                        SET mention_count = mention_count + %s
                        WHERE entity_name = %s AND entity_type = %s
                          AND mention_count >= %s
                        """,
                        (delta, *key, -delta),
                    )
                    if cursor.rowcount != 1:
                        raise ValueError("개체명 빈도표가 출현 원본과 일치하지 않습니다.")
                    cursor.execute(
                        """
                        DELETE FROM public.ner_entity_frequency
                        WHERE entity_name = %s AND entity_type = %s AND mention_count = 0
                        """,
                        key,
                    )

            cursor.execute("DELETE FROM public.ner_entity_location WHERE doc_id = %s", (doc_id,))
            cursor.execute(
                """
                INSERT INTO public.ner_entity_location
                    (press_id, entity_name, entity_type, file_id, doc_id,
                     paragraph_id, sentence_id, mention_count)
                SELECT press_id, entity_name, entity_type, file_id, doc_id,
                       paragraph_id, sentence_id, COUNT(*)
                FROM public.ner_entity_mentions WHERE doc_id = %s
                GROUP BY press_id, entity_name, entity_type, file_id,
                         doc_id, paragraph_id, sentence_id
                """,
                (doc_id,),
            )
            cursor.execute(
                """
                INSERT INTO public.ner_entity_refresh_log (doc_id, refreshed_at)
                VALUES (%s, CURRENT_TIMESTAMP)
                ON CONFLICT (doc_id) DO UPDATE SET refreshed_at = EXCLUDED.refreshed_at
                """,
                (doc_id,),
            )
    return sum(new.values())
