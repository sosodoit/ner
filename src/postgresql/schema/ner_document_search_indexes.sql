-- 기존 DB에서는 각 문장을 별도로 실행한다. CONCURRENTLY는 트랜잭션 밖에서 실행해야 한다.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 기사·문장 ID의 대소문자 무관 부분 검색(ILIKE '%검색어%')을 지원한다.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ner_documents_id_search
    ON public.ner_documents USING gin (doc_id gin_trgm_ops, sentence_id gin_trgm_ops);
