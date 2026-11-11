CREATE TABLE IF NOT EXISTS ner_corrected_sentences (
    -- 실행 및 주요 식별 정보
    run_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    sentence_id TEXT NOT NULL,

    -- LLM 수정 문장
    corrected_sentence TEXT,

    -- 휴먼검수 수정 문장
    human_corrected_sentence TEXT,

    -- 적재 정보
    load_dt DATE DEFAULT CURRENT_DATE,

    CONSTRAINT uq_ner_corrected_sentences
        UNIQUE (run_id, doc_id, sentence_id),

    FOREIGN KEY (run_id)
        REFERENCES ner_runs (run_id),

    FOREIGN KEY (doc_id, sentence_id)
        REFERENCES ner_documents (doc_id, sentence_id)
);

CREATE INDEX IF NOT EXISTS idx_ner_corrected_sentences_run_id
    ON ner_corrected_sentences (run_id);

CREATE INDEX IF NOT EXISTS idx_ner_corrected_sentences_doc_sentence
    ON ner_corrected_sentences (doc_id, sentence_id);