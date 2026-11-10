CREATE TABLE IF NOT EXISTS ner_rule_results (
    -- 주요 식별 정보
    run_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    sentence_id TEXT NOT NULL,
    entity_id TEXT,

    -- 검출 단위
    rule_unit TEXT NOT NULL,

    -- 룰 검출 결과 및 패턴
    rule_results JSONB NOT NULL,

    -- 적재 정보
    load_dt DATE DEFAULT CURRENT_DATE,

    -- 중복 방지
    CONSTRAINT uq_ner_rule_results
        UNIQUE NULLS NOT DISTINCT (
            run_id,
            doc_id,
            sentence_id,
            entity_id
        ),

    -- 실행 및 원문 데이터 연결
    FOREIGN KEY (doc_id, sentence_id)
        REFERENCES ner_documents (doc_id, sentence_id)
);

CREATE INDEX IF NOT EXISTS idx_ner_rule_results_run_id
    ON ner_rule_results (run_id);

CREATE INDEX IF NOT EXISTS idx_ner_rule_results_doc_sentence
    ON ner_rule_results (doc_id, sentence_id);
