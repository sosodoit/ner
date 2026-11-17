# NER Streamlit 앱 파일

## 폴더 구성

```text
src/
└── streamlit/
    ├── app.py
    ├── pages/
    │   ├── 1_전체_통계.py
    │   └── 2_NER_검수.py
    └── modules/
        ├── ner_summary_query.py
        └── summary_service.py
```

## 적용 방법

```bash
streamlit run src/streamlit/app.py
```

## 구현 범위

- 전체 통계: `ner_documents`의 언론사별 기사·문장 수 집계
- LLM 통계: `ner_reviews` 데이터 적재 후 구현할 위치만 확보
- NER 검수: 별도 빈 페이지로 구성

원본 데이터는 PostgreSQL에서 집계한 결과만 Python으로 전달. Streamlit 캐시 기본 유효 시간은 10분이며, 전체 통계 화면의 `집계 새로고침` 버튼으로 캐시 갱신 가능.
