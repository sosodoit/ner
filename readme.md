프로젝트 구조
```
ner/
├── data/
├── outputs/
├── analysis/
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
│       ├── lean_word.txt
│       ├── multilingual.txt
│       └── parentheses.txt
├── .env
├── extract_target_data.log
├── error_case_retriever.log
├── ner_reviewer.log
├── extract_target_data.py
├── error_case_retriever.py
└── ner_reviewer.py
```

data 폴더 구조
- 검수 대상 데이터가 들어오는 경로
- 폴더명 규칙: 검수 대상 데이터 버전명 + 생성되는 날짜 + 시간 `ex) poc_2610241558`
- 파일명 및 id 폴더 규칙: 언론사.json, id 폴더 아래 언론사.json (AI실 생성 규칙과 동일)

    ```
    ├── data/
    │   └── {이름_검수시간}/
    │       ├── {언론사}.json
    │       └── id/
    │           └── {언론사}.json
    ```

- 언론사.json 구조

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

- id/언론사.json 구조

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

환경 설정
- 패키지 설치

    ```bash
    pip install -r requirements.txt
    ```
- 환경변수 설정

    ```env
    OPENAI_API_KEY = your_api_key
    OPENROUTER = your_api_key
    ```