프로젝트 구조
```
ner/
├── data/
├── outputs/
├── analysis/
├── private/
├── prompts/
│   ├── system_prompt.txt
│   ├── all.txt
│   ├── ps.txt
│   ├── lc.txt
│   ├── og.txt
│   ├── af.txt
│   ├── dt.txt
│   ├── ev.txt
│   └── exception/
│       ├── common.txt
│       ├── multilingual.txt
│       └── parentheses.txt
├── .env
├── upload_to_bigquery.log
├── extract_target_data.log
├── error_case_retriever.log
├── ner_reviewer.log
├── upload_to_bigquery.py
├── extract_target_data.py
├── error_case_retriever.py
└── ner_reviewer.py
```

data 폴더 구조
- 검수 대상 데이터가 들어오는 경로
- 폴더명 규칙: 검수 대상 데이터 버전명 + 생성되는 날짜 + 시간 `ex) poc_2610241558`
- 파일명 및 id 폴더 규칙: 언론사.json, id 폴더 아래 언론사.json (AI실 생성 규칙과 동일)

    ```
    data/
    └── poc_2610241558/
        ├── 강원일보.json
        ├── 경기일보.json
        └── id/
            ├── 강원일보.json
            └── 경기일보.json
    ```
    <details>
    <summary>언론사.json 구조</summary>
    <div markdown="1">

    ```
    {
        "id": "",
        "metadata": {
            "title": "",
            "creator": "",
            "distributor": "",
            "year": "",
            "category": "",
            "annotation_level": [""],
            "sampling": ""
        },
        "document": [
            {
            "id": "",
            "metadata": {
                "title": "",
                "author": "",
                "publisher": "",
                "date": "",
                "topic": "",
                "original_topic": ""
            },
            "paragraph": [
                {
                "id": "",
                "sentence": [
                    {
                    "id": "",
                    "form": ""
                    }
                ]
                },
                ...
            ]
            }
            ...
        ]
    }
    ```
    
    </div>
    </details>

    <details>
    <summary>id/언론사.json 구조</summary>
    <div markdown="1">

    ```
    [
        {
            "data_version": "",
            "document_id": "",
            "unique_id": "",
            "title": "",
            "topic": ""
        },
        ...
    ]
    ```

    </div>
    </details>

outputs 폴더 구조
- 검수 결과 데이터가 들어오는 경로
- 폴더명 규칙: 검수 대상 데이터 버전명 + 생성되는 날짜 + 시간 `ex)  poc_2610241558_2610251730`
- 파일명: 언론사.json

    ```
    outputs/
    └── poc_2610241558_2610251730/
        ├── 강원일보.jsonl
        └── 경기일보.jsonl
    ```

    <details>
    <summary>언론사.jsonl 구조</summary>
    <div markdown="1">

    ```
    ...
    ```

    </div>
    </details>

환경 설정
- 패키지 설치

    ```bash
    pip install -r requirements.txt
    ```
- 환경변수 설정

    ```env
    OPENAI_API_KEY = ""
    OPENROUTER = ""

    GOOGLE_APPLICATION_CREDENTIALS = ""
    GCP_PROJECT_ID = ""
    GCP_DATASET_ID = ""
    GCP_TABLE_NAME = ""
    ```