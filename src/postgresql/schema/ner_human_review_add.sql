CREATE TABLE IF NOT EXISTS ner_human_review_add (
    data_version TEXT NOT NULL,
    press TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    sentence_id TEXT NOT NULL,
    original_form TEXT,
    modified_form TEXT,
    review_method TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT '미완료',
    is_modified BOOLEAN NOT NULL DEFAULT FALSE,
    assignee TEXT NOT NULL,
    updated_at TIMESTAMPTZ,

    CONSTRAINT uq_ner_human_review_add
        UNIQUE (data_version, press, doc_id, sentence_id),

    CONSTRAINT ck_ner_human_review_add_method
        CHECK (review_method IN ('일괄처리', 'LLM검수', '계엄기사')),

    CONSTRAINT ck_ner_human_review_add_status
        CHECK (review_status IN ('완료', '미완료'))
);

CREATE INDEX IF NOT EXISTS idx_ner_human_review_add_doc_sentence
    ON ner_human_review_add (doc_id, sentence_id);

CREATE INDEX IF NOT EXISTS idx_ner_human_review_add_assignee
    ON ner_human_review_add (assignee);
