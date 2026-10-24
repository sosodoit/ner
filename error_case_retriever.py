# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER Error Case Retriever
# * 작성일: 2026-10-24
# * 설명: NER 검수 오류 사례 선별 및 프롬프트 변환
# ***************************************************
import re
import json
import logging
import pandas as pd
from pathlib import Path
from collections import defaultdict

# ***************************************************
# * 로그 설정
# ***************************************************
LOG_FILE = Path(__file__).resolve().parent / "error_case_retriever.log"
retriever_logger = logging.getLogger("error_case_retriever")
retriever_logger.setLevel(logging.INFO)
retriever_logger.propagate = False
if not retriever_logger.handlers:
    handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    retriever_logger.addHandler(handler)

# ***************************************************
# * 오류 유형 맵핑
# ***************************************************
ERROR_LV1_MAP = {
    "태그오류": "tagging_error",
    "오태깅": "tagging_wrong",
    "태깅누락": "tagging_miss",
    "범위오류": "span_error",
    "기타": "etc",
}

ERROR_LV2_MAP = {
    "범위확장": "span_expansion",
    "범위축소": "span_reduction",
    "태깅분리": "span_tagging_split",
    "태깅병합": "span_tagging_merge",
}

ERROR_LV1 = list(ERROR_LV1_MAP.values())
ERROR_LV2 = list(ERROR_LV2_MAP.values())

# ***************************************************
# * 오류목록 엑셀파일로드 및 문장단위그룹화
# * - 개체명 단위로 작성되어 있기 때문에 문장 그룹화
# ***************************************************
def load_error_cases(error_file):
    error_list = pd.read_excel(error_file, sheet_name="오류목록", dtype=str).fillna("")
    total_rows = len(error_list)

    # 오류 행만 필터링
    error_list = error_list[error_list["검수결과"].str.strip().isin({"오류", "오류,추가"})]

    # 데이터버전, 문서ID, 문장ID가 같은 행을 하나의 문장 사례로 처리
    cases = {}
    for key, group in error_list.groupby(["데이터버전", "문서 ID", "문장 ID"], sort=False):
        cases[key] = {"form": group.iloc[0]["form"], "rows": group.to_dict("records")}

    retriever_logger.info(f"오류사례 로드완료: 전체행={total_rows} | 오류행={len(error_list)} | 문장사례={len(cases)}")
    return cases

# ***************************************************
# * 기존검수문장과 미검수문장 분리
# * - reviewed: 기존검수문장, unreviewed: 미검수문장
# ***************************************************
def split_reviewed_sentences(article_file, id_file, cases):
    # ID 파일에서 데이터버전 확인
    id_rows = json.loads(Path(id_file).read_text(encoding="utf-8-sig"))
    document_versions = {row["document_id"]: row["data_version"] for row in id_rows}
    article = json.loads(Path(article_file).read_text(encoding="utf-8-sig"))
    result = {}

    # 검수대상문장이 기존검수결과에 있는지 확인
    for document in article["document"]:
        document_id = document["id"]
        version = document_versions.get(document_id, "")
        reviewed = []
        unreviewed = []
        for paragraph in document["paragraph"]:
            for sentence in paragraph["sentence"]:
                key = (version, document_id, sentence["id"])
                if key in cases:
                    reviewed.append({"sentence_id": sentence["id"], "case": cases[key]})
                else:
                    unreviewed.append({"sentence_id": sentence["id"], "text": sentence["form"]})
        result[document_id] = {"reviewed": reviewed, "unreviewed": unreviewed}
        retriever_logger.info(f"검수상태 분리완료: {document_id} | 기존검수={len(reviewed)} | 미검수={len(unreviewed)}")

    return result

# ***************************************************
# * 기존 검수결과의 출력 형식 변환
# * - REVIEW_SCHEMA의 reviews 형식으로 변환
# ***************************************************
def convert_reviewed_cases(reviewed):
    reviews = []
    for item in reviewed:
        for row in item["case"]["rows"]:
            reason = "\n".join(filter(None, [row.get("검수의견", ""), row.get("검수의견상세", "")]))
            reviews.append({
                "sentence_id": item["sentence_id"],
                "target_span": row.get("현재태깅", ""),
                "corrected_span": row.get("정답태깅", ""),
                "error_lv1": ERROR_LV1_MAP.get(row.get("오류유형_LV1", ""), "etc"),
                "error_lv2": ERROR_LV2_MAP.get(row.get("오류유형_LV2", "")),
                "reason": reason,
                "review_needed": False,
            })
    return reviews

# ***************************************************
# * 오류유형 대표사례 프롬프트에 넣을 형식으로 변환
# ***************************************************
def format_representative_cases(selected):
    if not selected:
        return ""

    lines = [
        "[오류유형 대표사례 - 참고용]",
        "대표사례는 참고자료이며, 검수대상 문장의 실제 문맥을 우선하여 판단하세요.",
    ]
    for index, item in enumerate(selected, 1):
        lines.append(f"사례 {index} (유사 검수대상 문장 ID: {item['target_sentence_id']})")
        lines.append(f"문장: {item['case']['form']}")
        for review in convert_reviewed_cases([{"sentence_id": item["case_key"][2], "case": item["case"]}]):
            lines.append(
                f"현재 태깅: {review['target_span']} / 정답 태깅: {review['corrected_span']} / "
                f"오류유형: {review['error_lv1']} / {review['error_lv2'] or '-'} / 검수의견: {review['reason']}"
            )

    return "\n".join(lines)

# ***************************************************
# * 검수할 문장과 유사한 대표사례 최대 2건 선별
# * - 유사도 기준: Jaccard 유사도 + 개체명 태그 가중치
# * - 유사도 계산: (교집합 / 합집합) + (개체명 태그 교집합 * 0.15)
# * - 개체명 태그는 PS, EV, OG, LC, AF, DT로 분리해 비교
# ***************************************************
ENTITY_TAG_PATTERN = re.compile(r"<([^:>]+):\s*(PS|EV|OG|LC|AF|DT)>", re.IGNORECASE)
TEXT_PATTERN = re.compile(r"[가-힣A-Za-z0-9]+")

def _tokenize(text):
    # 개체명 표면형과 개체명 태그를 분리해 토큰화
    matches = ENTITY_TAG_PATTERN.findall(text)
    tokens = set(TEXT_PATTERN.findall(ENTITY_TAG_PATTERN.sub(" ", text.lower())))
    for entity, tag in matches:
        tokens.update(TEXT_PATTERN.findall(entity.lower()))
        tokens.add(f"<tag:{tag.lower()}>")
    return tokens

def select_representative_cases(unreviewed, cases, limit=2):
    targets = [
        (sentence["sentence_id"], _tokenize(sentence["text"]))
        for sentence in unreviewed
    ]

    # 공통토큰이 있는 대표사례만 비교하도록 토큰 색인 추가
    token_index = defaultdict(set)
    case_tokens = {}
    for case_key, case in cases.items():
        tokens = _tokenize(case["form"])
        if not tokens:
            continue
        case_tokens[case_key] = (tokens, {token for token in tokens if token.startswith("<")})
        for token in tokens:
            token_index[token].add(case_key)

    # 대표사례마다 가장 유사한 검수대상문장 확인
    best_matches = {}
    for sentence_id, target_tokens in targets:
        if not target_tokens:
            continue
        candidate_keys = set()
        for token in target_tokens:
            candidate_keys.update(token_index.get(token, set()))

        target_tags = {token for token in target_tokens if token.startswith("<")}
        for case_key in candidate_keys:
            case_token_set, case_tags = case_tokens[case_key]
            score = len(case_token_set & target_tokens) / len(case_token_set | target_tokens)
            score += len(case_tags & target_tags) * 0.15
            if score > best_matches.get(case_key, (0, ""))[0]:
                best_matches[case_key] = (score, sentence_id)

    # 유사도 기준 최대 2건 선택
    ranked = [
        (score, sentence_id, case_key, cases[case_key])
        for case_key, (score, sentence_id) in best_matches.items()
    ]
    selected = []
    for score, sentence_id, case_key, case in sorted(ranked, key=lambda item: item[0], reverse=True)[:limit]:
        selected.append({
            "score": score,
            "target_sentence_id": sentence_id,
            "case_key": case_key,
            "case": case,
        })

    retriever_logger.info(f"대표사례 선택완료: 미검수={len(unreviewed)} | 선택={len(selected)}")
    return selected
