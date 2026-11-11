# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER 검수 프롬프트 생성
# * 작성일: 2026-11-08
# * 수정일: 2026-11-11 (지시문 선배치, 기준 문서 파일명 헤더 추가)
# * 설명: 검수 지시문과 태그별 지침·예외사항을 결합하여 시스템 프롬프트 생성
# ***************************************************

# 검수 지시문 (절차·판정·출력 규칙)
INSTRUCTION_FILE = "system_prompt.txt"

# 기준 문서: system_prompt.txt 0절 적용 순서와 동일
# 헤더 이름은 지시문의 조항 참조('og.txt 7.12', 'og 7.12')와 일치시킴
REFERENCE_FILES = [
    ("all.txt", "tags/all.txt"),
    ("common.txt", "exception/common.txt"),
    ("ps.txt", "tags/ps.txt"),
    ("lc.txt", "tags/lc.txt"),
    ("og.txt", "tags/og.txt"),
    ("af.txt", "tags/af.txt"),
    ("dt.txt", "tags/dt.txt"),
    ("ev.txt", "tags/ev.txt"),
    ("parentheses.txt", "exception/parentheses.txt"),
    ("multilingual.txt", "exception/multilingual.txt"),
]

def read_prompt(path):
    return path.read_text(encoding="utf-8-sig").strip()

def build_system_prompt(prompt_dir):
    # 지시문을 앞에 두고 기준 문서를 뒤에 배치 (문서별 파일명 헤더로 조항 참조 식별)
    sections = [read_prompt(prompt_dir / INSTRUCTION_FILE), "# 기준 문서"]
    for name, relative_path in REFERENCE_FILES:
        sections.append(f"=== {name} ===\n{read_prompt(prompt_dir / relative_path)}")
    return "\n\n".join(sections)