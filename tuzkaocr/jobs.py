from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Literal, Optional


_FMT_EXT = {"alto": ".xml", "txt": ".txt"}


@dataclass
class Job:
    id: str
    status: Literal["queued", "running", "done", "failed"]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    result_paths: list[Path] = field(default_factory=list)
    error: Optional[str] = None
    mean_conf: Optional[float] = None
    n_lines: Optional[int] = None


class JobStoreFull(Exception):
    pass


class JobStore:
    def __init__(self, results_dir: str | Path, max_workers: int = 2,
                 max_job_age_hours: int = 24, max_queue: int = 16):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.RLock()
        self._results_dir = Path(results_dir)
        self._results_dir.mkdir(parents=True, exist_ok=True)
        self._executor = ThreadPoolExecutor(max_workers=max_workers,
                                            thread_name_prefix="tuzkaocr-worker")
        self._max_age = timedelta(hours=max_job_age_hours)
        self._max_queue = max_queue
        swept = self._sweep_orphans()
        if swept:
            print(f"[cleanup] removed {swept} orphaned result file(s) on startup", flush=True)

    def _active_count(self) -> int:
        return sum(1 for j in self._jobs.values()
                   if j.status in ("queued", "running"))

    def submit(self, process_fn: Callable[[], object], result_ext: str = ".xml") -> str:
        with self._lock:
            active = self._active_count()
            if active >= self._max_queue:
                raise JobStoreFull(
                    f"queue full ({active}/{self._max_queue})"
                )
            job_id = str(uuid.uuid4())
            self._jobs[job_id] = Job(id=job_id, status="queued")
        self._executor.submit(self._run, job_id, process_fn, result_ext)
        return job_id

    def _run(self, job_id: str, process_fn: Callable[[], object],
             result_ext: str = ".xml") -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.status = "running"
                job.started_at = datetime.now(timezone.utc)
        try:
            result = process_fn()
            meta: dict = {}
            if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
                result, meta = result
            paths: list[Path] = []
            if isinstance(result, dict):
                for key, content in result.items():
                    ext = _FMT_EXT.get(key)
                    if ext is None:
                        raise ValueError(f"Unknown multi-output key {key!r}")
                    p = self._results_dir / f"{job_id}{ext}"
                    p.write_text(content, encoding="utf-8")
                    paths.append(p)
            else:
                p = self._results_dir / f"{job_id}{result_ext}"
                p.write_text(result, encoding="utf-8")
                paths.append(p)
            with self._lock:
                job = self._jobs.get(job_id)
                if job:
                    job.status       = "done"
                    job.finished_at  = datetime.now(timezone.utc)
                    job.result_paths = paths
                    job.mean_conf    = meta.get("mean_conf")
                    job.n_lines      = meta.get("n_lines")
        except Exception as exc:
            with self._lock:
                job = self._jobs.get(job_id)
                if job:
                    job.status = "failed"
                    job.finished_at = datetime.now(timezone.utc)
                    job.error = str(exc)

    def has_capacity(self) -> bool:
        with self._lock:
            return self._active_count() < self._max_queue

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def get_result_path(self, job_id: str, which: Optional[str] = None) -> Optional[Path]:
        target_ext = _FMT_EXT.get(which) if which else None
        with self._lock:
            job = self._jobs.get(job_id)
            if job and job.result_paths:
                if target_ext:
                    for p in job.result_paths:
                        if p.suffix == target_ext and p.exists():
                            return p
                else:
                    for p in job.result_paths:
                        if p.exists():
                            return p
        if target_ext:
            p = self._results_dir / f"{job_id}{target_ext}"
            return p if p.exists() else None
        for ext in (".xml", ".txt"):
            p = self._results_dir / f"{job_id}{ext}"
            if p.exists():
                return p
        return None

    def pending_count(self) -> tuple[int, int]:
        with self._lock:
            queued = sum(1 for j in self._jobs.values() if j.status == "queued")
            running = sum(1 for j in self._jobs.values() if j.status == "running")
        return queued, running

    def cleanup(self) -> int:
        cutoff = datetime.now(timezone.utc) - self._max_age
        removed = 0
        with self._lock:
            to_delete = [
                jid for jid, job in self._jobs.items()
                if job.created_at < cutoff
            ]
            for jid in to_delete:
                job = self._jobs.pop(jid)
                for p in job.result_paths:
                    if p.exists():
                        p.unlink(missing_ok=True)
                removed += 1
        removed += self._sweep_orphans()
        return removed

    def _sweep_orphans(self) -> int:
        cutoff_ts = time.time() - self._max_age.total_seconds()
        removed = 0
        for p in self._results_dir.iterdir():
            if p.suffix not in (".xml", ".txt"):
                continue
            try:
                if p.stat().st_mtime < cutoff_ts:
                    p.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                continue
        return removed

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True)
