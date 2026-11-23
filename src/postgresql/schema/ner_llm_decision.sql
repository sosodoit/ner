CREATE TABLE IF NOT EXISTS ner_llm_decision (
    run_id TEXT NOT NULL,
    schema_version TEXT,
    data_version TEXT NOT NULL,
    press TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    sentence_id TEXT NOT NULL,
    executed_at TIMESTAMPTZ,
    model TEXT,
    prompt_version TEXT,
    status TEXT NOT NULL,
    original_form TEXT,
    decision_type TEXT NOT NULL,
    review_candidate BOOLEAN NOT NULL DEFAULT FALSE,
    low_confidence BOOLEAN NOT NULL DEFAULT FALSE,
    min_confidence DOUBLE PRECISION,
    tagging_error_is_error BOOLEAN,
    tagging_error_type TEXT,
    tagging_error_confidence DOUBLE PRECISION,
    tagging_error_probabilities JSONB,
    tagging_merge_needed BOOLEAN,
    tagging_merge_confidence DOUBLE PRECISION,
    tagging_merge_probabilities JSONB,
    review_reason JSONB,
    candidate_rule_ids JSONB,
    existing_entities JSONB,
    active_rule_evidence JSONB,
    api_usage JSONB,
    api_answers JSONB,
    load_dt TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_ner_llm_decision
        PRIMARY KEY (run_id, data_version, press, doc_id, sentence_id),
    CONSTRAINT ck_ner_llm_decision_type
        CHECK (decision_type IN ('normal', 'tagging_error', 'tagging_merge'))
);

CREATE INDEX IF NOT EXISTS idx_ner_llm_decision_lookup
    ON ner_llm_decision (data_version, press, doc_id, sentence_id);

CREATE INDEX IF NOT EXISTS idx_ner_llm_decision_review
    ON ner_llm_decision (press, decision_type, review_candidate, low_confidence);
