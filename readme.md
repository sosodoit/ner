### 프로젝트 구조

```text
ner/
├── data/                 # 검수 대상 데이터
├── outputs/              # 검수 결과
├── analysis/             # 검수 이력 Excel 등 분석 자료
├── private/              # 인증 파일 등 비공개 자료
├── prompts/              # LLM 검수 프롬프트
│   ├── tags/             # 공통 및 태그별 기준(af, dt, ev, lc, og, ps, all)
│   ├── system_prompt.txt
│   └── exception/        # 특수 상황별 기준
├── logs/                 # 실행 로그
└── src/
    ├── ner_review/
    │   ├── response.py
    │   ├── schema.py
    │   ├── prompt.py
    │   ├── result.py
    │   └── tokens.py
    ├── bigquery/
    │   └── load_reviews.py
    ├── legacy/
    │   └── google_sheets/
    │       ├── export_google_sheet.py
    │       ├── extract_human_corrections.py
    │       └── google_sheets_schema.py
    └── data_processing/
        ├── rule_pipeline.py
        ├── rules/
        │   ├── sentence_rules.py
        │   └── entity_rules.py
        ├── prepare/
        │   ├── ner_prepare_data.py
        │   └── ner_error_stat.py
        └── legacy/
            └── extract_target_data.py
```

### 설치 및 환경 설정

```bash
pip install -r requirements.txt
```

```env
OPENAI_API_KEY=""
OPENROUTER_API_KEY=""

GOOGLE_APPLICATION_CREDENTIALS=""
GOOGLE_APPLICATION_CREDENTIALS_DB=""
GCP_PROJECT_ID=""
GCP_DATASET_ID=""
GCP_TABLE_NAME=""
GOOGLE_SPREADSHEET_ID=""

DATA_VERSION=""
API_PROVIDER=""       
MODEL_NAME=""

LANGSMITH_TRACING=
LANGSMITH_PROJECT=
LANGSMITH_ENDPOINT=
LANGSMITH_API_KEY=
```