# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: NER 검수 프롬프트 생성
# * 작성일: 2026-11-08
# * 설명: 태그별 지침과 예외사항을 결합하여 시스템 프롬프트 생성
# ***************************************************
def read_prompt(path):
    return path.read_text(encoding="utf-8-sig").strip()

def build_system_prompt(prompt_dir):
    prompt_files = [
        prompt_dir / "tags/all.txt",
        prompt_dir / "tags/ps.txt",
        prompt_dir / "tags/lc.txt",
        prompt_dir / "tags/og.txt",
        prompt_dir / "tags/af.txt",
        prompt_dir / "tags/ev.txt",
        prompt_dir / "tags/dt.txt",
        prompt_dir / "exception/common.txt",
        prompt_dir / "exception/multilingual.txt",
        prompt_dir / "exception/parentheses.txt",
        prompt_dir / "system_prompt.txt",
    ]

    sections = []
    for path in prompt_files:
        sections.append(f"{read_prompt(path)}")

    return "\n\n".join(sections)
