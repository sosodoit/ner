CREATE TABLE IF NOT EXISTS ner_reviews (
    run_folder TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    prompt_version TEXT,
    dataset_version TEXT,
    press TEXT,
    doc_id TEXT NOT NULL,
    sentence_id TEXT NOT NULL,
    review_id TEXT,
    source_sentence TEXT,
    llm_review_status TEXT,
    review_status TEXT,
    target_span TEXT,
    target_type TEXT,
    corrected_span TEXT,
    error_lv1 TEXT,
    error_lv2 TEXT,
    reason TEXT,
    review_needed BOOLEAN,
    load_dt DATE
);

CREATE INDEX IF NOT EXISTS idx_ner_reviews_run_folder
    ON ner_reviews (run_folder);

CREATE INDEX IF NOT EXISTS idx_ner_reviews_doc_sentence
    ON ner_reviews (doc_id, sentence_id);
