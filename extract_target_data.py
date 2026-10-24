# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER 검수 대상 데이터 추출
# * 작성일: 2026-10-24
# * 설명: 지정한 문서ID의 기사와 고유ID 매핑 파일 생성
# ***************************************************
import json
import logging
import argparse
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOG_FILE = BASE_DIR / "extract_target_data.log"

TARGET_DOCUMENTS = {
    "강원일보": [
        {"id": "NLRW2600000001.2", "title": "<오세훈: PS>, <전용기: PS> ‘카톡 내란선동 고발’ 발언에 “사적 대화까지 검열” 비판"},
        {"id": "NLRW2600000001.1", "title": "<이재명: PS>, <강원도: LC>에 어떤 내용 공약했나"},
    ],
    "부산일보": [{"id": "NLRW2600000003.30", "title": "<한동훈: PS>, <尹: PS>부부 비방글 당원게시판 조사에 “당 퇴행시키는 시도”"}],
    "세계일보": [{"id": "NWRW2600000003.21", "title": "<韓·美: LC> 고위급 ‘원자력 긴밀 소통’ 합의 [<韓·美: LC> 정상회담 이후]"}],
    "충청일보": [{"id": "NLRW2600000004.24", "title": "세계를 잇는 통관의 지혜, <한국: LC>에서 배운다"}],
    "노컷뉴스": [{"id": "NIRW2600000001.13", "title": "<美中: LC>, 관세 유예 기간 ‘<90일: DT> 추가 연장’ 잠정 합의"}],
    "경향신문": [{"id": "NWRW2600000001.4", "title": "미사용 용적, 다른 지역에 매매…서울형 ‘용적률 거래제’ 재추진"}],
    "스포츠투데이": [{"id": "NPRW2600000003.15", "title": "<쿠팡플레이: OG>, <카라바오컵: EV> 4강 2차전·<FA컵: EV> 4라운드 생중계"}],
    "뉴스1": [{"id": "NZRW2600000001.8", "title": "<제이지스타: OG> “<임창정: PS>, 공연 개런티 손해액 변제 불이행…법적 대응”"}],
    "마이데일리": [{"id": "NIRW2600000002.21", "title": "‘GOAT’의 품격...<메시: PS> 멀티골 폭발! <인터 마이애미: OG>, PO 1차전 3-1 ‘완승’→2라운드 진출 ‘청신호’"}],
    "스포츠경향": [{"id": "NPRW2600000002.24", "title": "이번에도 <호주: OG>가 최강이었다···<중국: OG> 잡고 <FIBA 아시아컵: EV> 3회 연속 우승"}],
    "아시아투데이": [{"id": "NWRW2600000004.6", "title": "<사발렌카: PS>, 여자 테니스 ‘올해의 선수’ 수상… <2년: DT> 연속 영예"}],
    "뉴스핌": [{"id": "NZRW2600000002.6", "title": "[프로필] <임채원: PS> 신임 <국가공무원인재개발원: OG>장…“공직 사회·리더십 교육 전문성 갖춰”"}],
    "이투데이": [{"id": "NPRW2600000005.9", "title": "<풀무원샘물: OG>, <지구의 날: EV> 맞아 <월드비전: OG>과 ‘플로깅 런’"}],
    "디지털타임스": [{"id": "NPRW2600000001.12", "title": "<체코: LC> 원전 최종 계약까지…남은 법적 절차는"}],
    "일간투데이": [{"id": "NWRW2600000005.13", "title": "<국립공주박물관: OG>, 특별전 “<한성, 475-두 왕의 승부수: EV>” 개최"}],
    "뉴시스": [{"id": "NZRW2600000003.30", "title": "<진주시 여성자원봉사대: OG>, 봉사대상 ‘<행안부: OG> 장관상’ 수상"}],
    "서울신문": [{"id": "NWRW2600000002.13", "title": "화엄의 빛 ‘<법성게: AF>’ 천년을 넘어 법성의 소리로 살아나다"}],
    "경기일보": [{"id": "NLRW2600000002.14", "title": "<정부: OG>, <형제복지원: OG> 국가배상 소송 상소 전면 포기"}],
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()])

# ***************************************************
# * 데이터 추출
# * 1. 지정한 문서ID의 기사 추출 (문서ID와 제목이 모두 일치하는 문서만 추출)
# * 2. 고유ID 매핑 파일 생성
# * 3. 결과 저장
# ***************************************************
read_json = lambda path: json.loads(path.read_text(encoding="utf-8-sig"))

def main():
    # 실행 옵션 설정
    parser = argparse.ArgumentParser(description="NER 검수 대상 데이터 추출")
    parser.add_argument("--input-dir", nargs="+", default=["temp/19outlets_30ea(1002)", "temp/17outlets_50ea(0921)"])
    parser.add_argument("--output-name", default="poc")
    parser.add_argument("--target-file", type=Path)
    args = parser.parse_args()

    # 출력 경로 설정
    output_dir = BASE_DIR / "data" / f"{args.output_name}_{datetime.now().strftime('%y%m%d%H%M')}"
    mapping_dir = output_dir / "id"
    output_dir.mkdir(parents=True, exist_ok=True)
    mapping_dir.mkdir(exist_ok=True)

    # 추출 대상 데이터 설정
    target_documents = TARGET_DOCUMENTS # 임시
    if args.target_file:
        target_documents = read_json(args.target_file)

    results = {}
    mappings = {}

    # 입력 데이터 순회
    # - 추출해야하는 데이터 버전이 여러 개일 경우(폴더가 여러 개일 경우) 대비하여 입력 디렉토리 리스트를 순회
    for input_name in args.input_dir:
        input_dir = BASE_DIR / input_name
        corpus_dir = input_dir / "ner" / "outputs" / "corpus_4_ner_tagged"
        id_dir = input_dir / "id"
        data_version = input_dir.name

        # 언론사별 문서 순회
        # - 입력 데이터 폴더에 언론사별로 문서가 존재함
        # - 추출 대상 문서가 없는 언론사는 건너뜀
        for outlet, targets in target_documents.items():
            corpus_path = corpus_dir / f"{outlet}.json"
            id_path = id_dir / f"{outlet}.json"

            # 추출하려는 언론사 파일 존재 확인
            if not corpus_path.is_file() or not id_path.is_file():
                logging.warning(f"매핑파일없음: {input_name} | {outlet}")
                continue

            corpus = read_json(corpus_path)
            id_map = read_json(id_path)
            documents = []
            mapping = []

            # 추출 대상 문서 순회
            # - 문서 내 문서ID(기사)가 여러 건 존재함
            # - 문서ID와 제목이 모두 일치하는 문서만 추출
            for target in targets:
                target_id = target["id"]
                target_title = target["title"]
                matched = [document for document in corpus["document"] if document["id"] == target_id and (not target_title or document["paragraph"][0]["sentence"][0]["form"] == target_title)]

                if len(matched) != 1:
                    logging.warning(f"매핑문서없음: {input_name} | {outlet} | {target_id} | {target_title}")
                    continue
                
                logging.info(f"매핑문서존재: {input_name} | {outlet} | {target_id} | {target_title}")
                
                # 문서 및 매핑 정보 생성
                document = {**matched[0], "unique_id": id_map[target_id]}
                title = document["paragraph"][0]["sentence"][0]["form"]
                documents.append(document)
                mapping.append({
                    "data_version": data_version,
                    "document_id": target_id,
                    "unique_id": id_map[target_id],
                    "title": title,
                    "topic": f"{document['metadata'].get('topic', '')} | {document['metadata'].get('original_topic', '')}",
                })

            # 추출 문서가 없으면 저장하지 않음
            if not documents:
                logging.warning(f"저장문서없음: {input_name} | {outlet}")
                continue

            # 언론사별 결과 누적
            if outlet not in results:
                results[outlet] = {key: value for key, value in corpus.items() if key != "document"}
                results[outlet]["document"] = []
                mappings[outlet] = []
            
            results[outlet]["document"].extend(documents)
            mappings[outlet].extend(mapping)
            logging.info(f"추출완료: {input_name} | {outlet} | {len(documents)}건")

    # 저장
    for outlet, result in results.items():
        (output_dir / f"{outlet}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (mapping_dir / f"{outlet}.json").write_text(json.dumps(mappings[outlet], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    logging.info(f"결과저장완료: {output_dir}")

if __name__ == "__main__":
    main()
