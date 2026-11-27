# -*- coding: utf-8 -*-
"""계엄기사 검수 화면."""

import runpy
from pathlib import Path


runpy.run_path(
    str(Path(__file__).with_name("1_ner.py")),
    init_globals={"REVIEW_PAGE_METHOD": "휴먼검수"},
)
