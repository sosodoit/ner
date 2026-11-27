# -*- coding: utf-8 -*-
"""개체명 목록 생성과 검수 화면에서 공유하는 태그 형식."""

# 개체명 안의 콜론은 보존하고, 닫는 괄호 직전의 분류코드로 구분한다.
# Python과 PostgreSQL에서 모두 사용하므로 캡처 그룹은 개체명·분류 두 개만 둔다.
ENTITY_TAG_PATTERN = r"<\s*([^<>]+?)\s*:\s*(PS|LC|OG|AF|DT|EV)\s*>"
