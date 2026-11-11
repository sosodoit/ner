CREATE TABLE IF NOT EXISTS ner_reviews (
    -- 실행 및 주요 식별 정보
    run_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    sentence_id TEXT NOT NULL,
    entity_id TEXT,

    -- 검수 대상 정보
    target_span TEXT,
    target_type TEXT,

    -- LLM 검수 결과
    corrected_span TEXT,
    error_lv1 TEXT,
    error_lv2 TEXT,
    reason TEXT,
    review_needed BOOLEAN,

    -- 검수 상태
    llm_review_status TEXT,
    review_status TEXT,

    -- 적재 정보
    load_dt DATE DEFAULT CURRENT_DATE,

    CONSTRAINT uq_ner_reviews
        UNIQUE NULLS NOT DISTINCT (
            run_id, doc_id, sentence_id, entity_id
        ),

    FOREIGN KEY (run_id)
        REFERENCES ner_runs (run_id),

    FOREIGN KEY (doc_id, sentence_id)
        REFERENCES ner_documents (doc_id, sentence_id)
);

CREATE INDEX IF NOT EXISTS idx_ner_reviews_run_id
    ON ner_reviews (run_id);

CREATE INDEX IF NOT EXISTS idx_ner_reviews_doc_sentence
    ON ner_reviews (doc_id, sentence_id);

CREATE INDEX IF NOT EXISTS idx_ner_reviews_review_status
    ON ner_reviews (review_status);