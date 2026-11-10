CREATE TABLE IF NOT EXISTS ner_documents (
    -- 주요 식별 정보
    doc_id TEXT NOT NULL,
    document_order INTEGER NOT NULL,
    paragraph_id TEXT NOT NULL,
    sentence_id TEXT NOT NULL,

    -- 말뭉치 메타정보
    corpus_metadata JSONB,

    -- 기사 메타정보
    document_title TEXT,
    author TEXT,
    publisher TEXT,
    date TEXT,
    topic TEXT,
    original_topic TEXT,

    -- 문장 정보
    form TEXT NOT NULL,
    paragraph_order INTEGER,
    sentence_order INTEGER,

    -- 적재 정보
    load_dt DATE DEFAULT CURRENT_DATE,

    PRIMARY KEY (doc_id, sentence_id)
);

CREATE INDEX IF NOT EXISTS idx_ner_documents_publisher
    ON ner_documents (publisher);