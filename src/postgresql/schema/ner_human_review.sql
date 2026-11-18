CREATE TABLE IF NOT EXISTS ner_human_review (
    data_version TEXT NOT NULL,
    press TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    sentence_id TEXT NOT NULL,
    original_form TEXT,
    modified_form TEXT,
    review_method TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT '미완료',
    is_modified BOOLEAN NOT NULL DEFAULT FALSE,
    assignee TEXT,
    updated_at TIMESTAMPTZ,

    CONSTRAINT uq_ner_human_review
        UNIQUE (data_version, press, doc_id, sentence_id),

    CONSTRAINT ck_ner_human_review_method
        CHECK (review_method IN ('일괄처리', 'LLM검수', '휴먼검수')),

    CONSTRAINT ck_ner_human_review_status
        CHECK (review_status IN ('완료', '미완료'))
);

CREATE INDEX IF NOT EXISTS idx_ner_human_review_press
    ON ner_human_review (press);

CREATE INDEX IF NOT EXISTS idx_ner_human_review_status
    ON ner_human_review (review_status);

CREATE INDEX IF NOT EXISTS idx_ner_human_review_doc_sentence
    ON ner_human_review (doc_id, sentence_id);
