CREATE TABLE IF NOT EXISTS ner_decision_results (
    run_id TEXT NOT NULL,
    data_version TEXT NOT NULL,
    press TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    sentence_id TEXT NOT NULL,

    -- 검출 정보
    detected_entities TEXT,
    candidate_rule_ids TEXT,

    -- 태그오류 판단
    tagging_error_probability DOUBLE PRECISION NOT NULL,
    tagging_error_confidence DOUBLE PRECISION NOT NULL,
    tagging_error_result TEXT NOT NULL,

    -- 태깅병합 판단
    tagging_merge_probability DOUBLE PRECISION NOT NULL,
    tagging_merge_confidence DOUBLE PRECISION NOT NULL,
    tagging_merge_result TEXT NOT NULL,

    -- Response 대상 여부
    review_candidate BOOLEAN NOT NULL DEFAULT FALSE,

    -- 적재 일시
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_ner_decision_results
        UNIQUE (data_version, press, doc_id, sentence_id),

    CONSTRAINT ck_ner_decision_tagging_error_result
        CHECK (tagging_error_result IN ('강한 의심', '중간 의심', '약한 의심')),

    CONSTRAINT ck_ner_decision_tagging_merge_result
        CHECK (tagging_merge_result IN ('강한 의심', '중간 의심', '약한 의심'))
);

CREATE INDEX IF NOT EXISTS idx_ner_decision_results_press
    ON ner_decision_results (press);

CREATE INDEX IF NOT EXISTS idx_ner_decision_results_doc_sentence
    ON ner_decision_results (doc_id, sentence_id);