# NER 검수 프로젝트

## 프로젝트 구조

```text
ner/
├── data/                 # 검수 대상 데이터
├── outputs/              # 검수 결과
├── analysis/             # 검수 이력 Excel 등 분석 자료
├── private/              # 인증 파일 등 비공개 자료
├── prompts/              # LLM 검수 프롬프트
├── logs/                 # 실행 로그
└── src/
    ├── llm_review/
    │   ├── ner_reviewer.py
    │   └── error_case_retriever.py
    ├── bigquery/
    │   └── load_reviews.py
    ├── google_sheets/
    │   ├── export_google_sheet.py
    │   ├── extract_human_corrections.py
    │   └── google_sheets_schema.py
    └── data_processing/
        └── extract_target_data.py
```

모든 명령은 저장소 루트(`ner/`)에서 실행합니다. Python 모듈은 프로젝트 루트를 기준으로 `data/`, `outputs/`, `analysis/`, `prompts/`, `.env`, `logs/`를 찾습니다.

## 설치 및 환경 설정

```bash
pip install -r requirements.txt
```

루트의 `.env`에 사용하는 서비스의 값을 설정합니다.

```env
DATA_VERSION=poc_...
API_PROVIDER=OPENAI                 # 또는 OPENROUTER
MODEL_NAME=gpt-4.1
OPENAI_API_KEY=
OPENROUTER_API_KEY=
GOOGLE_APPLICATION_CREDENTIALS=
GCP_PROJECT_ID=
GCP_DATASET_ID=
GCP_TABLE_NAME=
GOOGLE_SPREADSHEET_ID=
GOOGLE_DRIVE_FOLDER_ID=
```

## 기능별 실행 방법

### 1. 검수 대상 데이터 추출

입력 폴더와 출력 이름을 직접 지정하여 검수용 `data/<버전>/`을 생성합니다.

```bash
python -m src.data_processing.extract_target_data \
  --input-dir temp/19outlets_30ea(1002) temp/17outlets_50ea(0921) \
  --output-name poc \
  --target-file analysis/target.json
```

### 2. LLM NER 검수

`data/<data-version>/*.json`을 읽어 `outputs/<data-version>/<run-id>/reports/`에 결과를 저장합니다.

```bash
python -m src.llm_review.ner_reviewer --data-version poc_20261025_180000
```

### 3. 검수 오류 사례 조회

`error_case_retriever.py`는 LLM 검수에서 사용하는 오류 사례 조회 라이브러리입니다. 별도 실행 명령은 없으며 `ner_reviewer`가 자동으로 호출합니다.

### 4. BigQuery 적재

LLM 검수 결과가 있는 `outputs/` 하위 run 경로를 지정합니다.

```bash
python -m src.bigquery.load_reviews poc_20261025_180000/run_20261025_183000
```

### 5. BigQuery 결과를 Google Sheets로 내보내기

```bash
python -m src.google_sheets.export_google_sheet \
  poc_20261025_180000/run_20261025_183000
```

필요하면 시트 이름이나 기존 Spreadsheet ID를 지정할 수 있습니다.

```bash
python -m src.google_sheets.export_google_sheet <run-folder> \
  --sheet-name "NER 검수 결과" \
  --spreadsheet-id <spreadsheet-id>
```

### 6. Google Sheets 수정 결과 추출

시트에서 `human_status=수정완료`인 행을 JSON으로 추출합니다.

```bash
python -m src.google_sheets.extract_human_corrections \
  --spreadsheet-id <spreadsheet-id> \
  --output outputs/human_corrections.json
```

중복 또는 필수값 누락이 있으면 추출을 중단하고 같은 위치에 `.errors.json`을 생성합니다.

## 주요 입출력 형식

- `data/<버전>/<언론사>.json`: `document → paragraph → sentence` 구조의 검수 대상 원천 데이터
- `data/<버전>/id/<언론사>.json`: 문서 ID 매핑 자료
- `outputs/<버전>/<run-id>/reports/<언론사>/reviews.jsonl`: LLM 검수 결과
- `logs/*.log`: 각 기능의 실행 로그
