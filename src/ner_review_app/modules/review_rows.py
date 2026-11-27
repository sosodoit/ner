# -*- coding: utf-8 -*-
"""세 검수 화면이 공유하는 배정 기사 목록·본문 조회 캐시."""
#---------------------------------------------------------------------------------------------------------
# 기본 설정 - 라이브러리 및 데이터베이스 연결 모듈
#---------------------------------------------------------------------------------------------------------
from threading import Lock

import streamlit as st
from src.ner_review_app.modules.postgredb import get_postgre_connect


#---------------------------------------------------------------------------------------------------------
# 데이터 조회 - 검수 기사 및 본문 조회 결과 캐시
#---------------------------------------------------------------------------------------------------------
@st.cache_data(ttl=3600, max_entries=64, show_spinner=False)
def load_review_rows(query, params, cache_version=0):
    with get_postgre_connect() as conn:
        return conn.execute(query, params).fetchall()


@st.cache_resource
def _review_cache_versions():
    return Lock(), {}


def review_cache_version(press, assignee=None, doc_id=None):
    """담당자 목록 또는 기사 본문의 최신 캐시 버전."""
    lock, versions = _review_cache_versions()
    with lock:
        return versions.get((press, assignee, doc_id), 0)


def invalidate_review_rows(press, assignee, doc_ids, status_changed=True):
    """저장한 담당자의 목록과 해당 기사 본문만 갱신."""
    lock, versions = _review_cache_versions()
    with lock:
        keys = {(press, None, doc_id) for doc_id in doc_ids}
        if status_changed:
            keys.add((press, assignee, None))
        for key in keys:
            versions[key] = versions.get(key, 0) + 1
