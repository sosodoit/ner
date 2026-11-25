# -*- coding: utf-8 -*-
# ***************************************************
# * 모듈명: Response 문서 상태 및 결과 저장
# * 작성일: 2026-11-24
# * 설명: 언론사별 체크포인트와 JSONL·Parquet 결과 생성
# ***************************************************
import json
import os
import shutil
from contextlib import contextmanager
from datetime import date, datetime, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from .result import save_review_result, write_jsonl


def now():
    return datetime.now(timezone.utc).isoformat()


def load_date():
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


@contextmanager
def atomic_path(path):
    temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        yield temp
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def write_json(path, value):
    with atomic_path(path) as temp, temp.open("w", encoding="utf-8") as out:
        write_jsonl(out, value)


def run_metadata(root, provider, model, data_version, prompt_version, hashes):
    from .storage import save_run_parquet

    path = root / "run.jsonl"
    meta = dict(run_id=root.name, provider=provider, model=model,
                data_version=data_version, prompt_version=prompt_version)
    if path.exists():
        stored = json.loads(path.read_text(encoding="utf-8"))
        if any(stored[k] != value for k, value in meta.items()):
            raise ValueError(f"기존 실행과 provider/model/version이 다릅니다. 출력 경로를 확인하세요: {root}")
        if any(key in stored and stored[key] != value for key, value in hashes.items()):
            raise ValueError(f"기존 실행과 프롬프트 또는 후처리가 다릅니다. 새 실행 라벨을 사용하세요: {root}")
        meta = stored
    else:
        meta.update(hashes)
        meta["load_dt"] = load_date().isoformat()
        write_json(path, meta)
    if not (root / "ner_runs.parquet").exists():
        with atomic_path(root / "ner_runs.parquet") as temp:
            save_run_parquet(temp, meta)
    return meta


class ResponseState:
    """SQLite 커밋이 완료 기준이다. 중단된 파일 내보내기는 다음 실행에서 복구한다."""

    def __init__(self, db, directory, run_id, press):
        self.db = db
        self.directory = directory
        self.run_id = run_id
        self.press = press
        db.execute("PRAGMA locking_mode=EXCLUSIVE")
        db.execute("BEGIN EXCLUSIVE")
        fresh = not db.execute("SELECT 1 FROM sqlite_master WHERE name='documents'").fetchone()
        if fresh:
            # 완료 표식이 없는 예전 reviews에는 중간에 잘린 문서나 fallback이 있을 수 있다.
            for name in ("reviews.jsonl", "results.jsonl", "failures.jsonl", "ner_reviews.parquet"):
                path = directory / name
                if path.exists():
                    backup = directory / "before_manifest"
                    backup.mkdir(exist_ok=True)
                    shutil.copy2(path, backup / name)
        db.execute("""CREATE TABLE IF NOT EXISTS documents (
            doc_id TEXT PRIMARY KEY, status TEXT DEFAULT 'pending', attempts INTEGER DEFAULT 0,
            retries INTEGER DEFAULT 0, result TEXT, error TEXT, load_dt TEXT)""")
        db.execute("CREATE TABLE IF NOT EXISTS failures (record TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS active_batch (id INTEGER PRIMARY KEY, job TEXT)")
        db.commit()

    def select(self, ids, force):
        with self.db:
            self.db.execute("CREATE TEMP TABLE selected (doc_id TEXT PRIMARY KEY)")
            self.db.executemany("INSERT INTO selected VALUES (?)", ((key,) for key in ids))
            self.db.execute("INSERT OR IGNORE INTO documents(doc_id) SELECT doc_id FROM selected")
            if force:
                self.db.execute("""UPDATE documents SET status='pending', result=NULL
                                   WHERE doc_id IN (SELECT doc_id FROM selected)""")
        return [r[0] for r in self.db.execute("""
            SELECT doc_id FROM documents JOIN selected USING(doc_id)
            WHERE status != 'completed' ORDER BY (status='failed') DESC, selected.rowid
        """)]

    def job(self):
        row = self.db.execute("SELECT job FROM active_batch").fetchone()
        return json.loads(row[0]) if row else None

    def set_job(self, job):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO active_batch VALUES(1, ?)", (json.dumps(job),))

    def log(self, event, **fields):
        path = self.directory / "execution.log.jsonl"
        with path.open("a", encoding="utf-8") as out:
            write_jsonl(out, {"at": now(), "event": event, **fields})

    def summary(self, info, status, *, finished=False):
        counts = dict(self.db.execute("SELECT status, count(*) FROM documents GROUP BY status"))
        retries, = self.db.execute("SELECT coalesce(sum(retries), 0) FROM documents").fetchone()
        if status == "completed":
            if counts.get("pending"):
                status = "partial"
            elif counts.get("failed"):
                status = "completed_with_failures"
        summary = dict(info, status=status, total=sum(counts.values()), retry_count=retries,
                       finished_at=now() if finished else None)
        summary.update({key: counts.get(key, 0) for key in ("pending", "failed", "completed")})
        write_json(self.directory / "summary.json", summary)
        return summary

    def _write_document(self, results, reviews, doc_id, status, attempts, result):
        if status == "completed":
            write_jsonl(results, {"run_id": self.run_id, "doc_id": doc_id,
                                  "status": status, "attempts": attempts, "result": result})
        save_review_result(reviews, {"id": doc_id}, self.run_id, [], result=result)

    def export_documents(self):
        with (atomic_path(self.directory / "results.jsonl") as result_path,
              atomic_path(self.directory / "reviews.jsonl") as review_path,
              result_path.open("w", encoding="utf-8") as results,
              review_path.open("w", encoding="utf-8") as reviews):
            for key, status, attempts, result in self.db.execute(
                "SELECT doc_id,status,attempts,result FROM documents WHERE result IS NOT NULL"
            ):
                self._write_document(results, reviews, key, status, attempts, json.loads(result))

    def restore_exports(self):
        self.export_documents()
        with (atomic_path(self.directory / "failures.jsonl") as path,
              path.open("w", encoding="utf-8") as out):
            for record, in self.db.execute("SELECT record FROM failures ORDER BY rowid"):
                write_jsonl(out, json.loads(record))
        # 강제 종료 시 잘린 마지막 로그만 정리하고 기존 이벤트를 유지한다.
        path = self.directory / "execution.log.jsonl"
        if path.exists() and path.stat().st_size:
            with path.open("rb+") as log:
                log.seek(-1, os.SEEK_END)
                if log.read(1) != b"\n":
                    pos = log.tell()
                    while pos:
                        start = max(0, pos - 8192)
                        log.seek(start)
                        end = log.read(pos - start).rfind(b"\n")
                        if end >= 0:
                            pos = start + end + 1
                            break
                        pos = start
                    log.truncate(pos)

    def save(self, outcomes, *, finish_job=False, checkpoint_each=False):
        changes, failures = [], []
        replace = False
        with self.db:
            for key, attempts, result, error in outcomes:
                previous, old_attempts, has_result = self.db.execute(
                    "SELECT status,attempts,result IS NOT NULL FROM documents WHERE doc_id=?", (key,)
                ).fetchone()
                replace |= bool(has_result)
                total_attempts = old_attempts + attempts
                retries = max(0, attempts - 1) + int(previous == "failed" and attempts > 0)
                status = "failed" if error else "completed"
                if error:
                    record = dict(run_id=self.run_id, doc_id=key, status=status, at=now(),
                                  attempts=total_attempts, attempt_count=attempts, error=error)
                    self.db.execute("INSERT INTO failures VALUES (?)", (json.dumps(record),))
                    failures.append(record)
                self.db.execute("""
                    UPDATE documents SET status=?, attempts=?, retries=retries+?, result=?,
                        error=coalesce(?, error), load_dt=? WHERE doc_id=?
                """, (status, total_attempts, retries, json.dumps(result, ensure_ascii=False),
                      json.dumps(error, ensure_ascii=False) if error else None, load_date().isoformat(), key))
                changes.append((key, status, total_attempts, result))
                if checkpoint_each:
                    self.db.commit()
            if finish_job:
                self.db.execute("DELETE FROM active_batch")

        if replace:
            self.export_documents()
        else:
            with ((self.directory / "results.jsonl").open("a", encoding="utf-8") as results,
                  (self.directory / "reviews.jsonl").open("a", encoding="utf-8") as reviews):
                for change in changes:
                    self._write_document(results, reviews, *change)
        with (self.directory / "failures.jsonl").open("a", encoding="utf-8") as out:
            for record in failures:
                write_jsonl(out, record)
                self.log("document_failed", doc_id=record["doc_id"], error=record["error"])
        self.log("batch_saved", completed=len(changes)-len(failures), failed=len(failures))

    def export_parquet(self):
        import pyarrow as pa
        import pyarrow.parquet as pq

        from .storage import REVIEW_COLUMNS, build_parquet_rows

        types = {"review_needed": pa.bool_(), "load_dt": pa.date32()}
        schema = pa.schema([(col, types.get(col, pa.string())) for col in REVIEW_COLUMNS])
        with (atomic_path(self.directory / "ner_reviews.parquet") as path,
              pq.ParquetWriter(path, schema) as writer):
            rows = []
            for key, result, day in self.db.execute(
                "SELECT doc_id,result,load_dt FROM documents WHERE result IS NOT NULL"
            ):
                rows.extend(build_parquet_rows(json.loads(result), {"id": key}, self.run_id,
                                               self.press, date.fromisoformat(day)))
                if len(rows) >= 4096:
                    writer.write_table(pa.Table.from_pylist(rows, schema=schema))
                    rows.clear()
            if rows:
                writer.write_table(pa.Table.from_pylist(rows, schema=schema))
