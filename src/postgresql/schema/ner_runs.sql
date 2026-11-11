CREATE TABLE IF NOT EXISTS ner_runs (
    run_id TEXT PRIMARY KEY,
    provider TEXT,
    model TEXT,
    prompt_version TEXT,
    data_version TEXT,
    load_dt DATE DEFAULT CURRENT_DATE
);