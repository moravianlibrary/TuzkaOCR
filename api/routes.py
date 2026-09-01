from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Security, UploadFile, File
from fastapi.responses import PlainTextResponse
from fastapi.security.api_key import APIKeyHeader

from tuzkaocr import _models
from tuzkaocr.images import ImageDecodeError, decode_image_path
from tuzkaocr.jobs import JobInputError, JobStoreFull

ALLOWED_DOMAINS = {"kramarky", "handwritten", "kurrent"}
ALLOWED_FMTS = {"alto", "txt", "multi"}
ALLOWED_WHICH = {"alto", "txt"}
SPOOL_PREFIX = "tuzkaocr-upload-"

router = APIRouter()
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


@router.get("/healthz")
async def healthz():
    return {"status": "ok"}


class _KeyStore:
    TTL = 10

    def __init__(self):
        self._keys: dict[str, str] = {}
        self._path: Optional[str] = None
        self._loaded_at: float = 0.0
        self._lock = threading.Lock()

    def load(self, path: str) -> None:
        with self._lock:
            if path == self._path and time.monotonic() - self._loaded_at < self.TTL:
                return
            try:
                with open(path) as f:
                    raw = yaml.safe_load(f) or {}
                self._keys = {v: k for k, v in raw.items()}
            except FileNotFoundError:
                self._keys = {}
            except yaml.YAMLError as exc:
                print(f"[auth] failed to parse {path}: {exc}", flush=True)
                self._keys = {}
            self._path = path
            self._loaded_at = time.monotonic()

    def lookup(self, key: str) -> Optional[str]:
        return self._keys.get(key)


_key_store = _KeyStore()


def _require_key(request: Request, key: Optional[str] = Security(_api_key_header)) -> Optional[str]:
    cfg = request.app.state.config

    if cfg.api_keys_file:
        _key_store.load(cfg.api_keys_file)
        name = _key_store.lookup(key or "")
        if name is None:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        return name

    if cfg.api_key:
        if key != cfg.api_key:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        return "default"

    return None


def _validate_domain(domain: Optional[str]) -> Optional[str]:
    if domain in (None, "", "default", "print", "printed"):
        return None
    if domain not in ALLOWED_DOMAINS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown domain '{domain}'. Allowed: {['default'] + sorted(ALLOWED_DOMAINS)}",
        )
    return domain


def _validate_fmt(fmt: Optional[str]) -> str:
    if fmt in (None, ""):
        return "alto"
    if fmt not in ALLOWED_FMTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown fmt '{fmt}'. Allowed: {sorted(ALLOWED_FMTS)}",
        )
    return fmt


def _spool_directory(spool_dir: Optional[str]) -> Path:
    return Path(spool_dir) if spool_dir else Path(tempfile.gettempdir())


def _unlink_spool(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        print(f"[cleanup] failed to remove upload spool {path}: {exc}", flush=True)


def sweep_spool_files(spool_dir: Optional[str]) -> int:
    directory = _spool_directory(spool_dir)
    removed = 0
    try:
        paths = list(directory.glob(f"{SPOOL_PREFIX}*"))
    except OSError:
        return 0
    for path in paths:
        try:
            if path.is_file():
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed


async def _read_upload(upload: UploadFile, spool_dir: Optional[str] = None) -> Path:
    directory = _spool_directory(spool_dir)
    spool = tempfile.NamedTemporaryFile(
        mode="wb",
        prefix=SPOOL_PREFIX,
        dir=directory,
        delete=False,
    )
    path = Path(spool.name)
    try:
        with spool:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                spool.write(chunk)
            spool.flush()
        return path
    except Exception:
        _unlink_spool(path)
        raise


def _submit(request: Request, spool_path: Path, page_id: str,
            domain: Optional[str],
            caller: Optional[str], fmt: Optional[str] = None,
            role_classifier: Optional[bool] = None) -> str:
    domain = _validate_domain(domain)
    fmt = _validate_fmt(fmt)
    cache = request.app.state.cache
    store = request.app.state.store
    max_image_pixels = request.app.state.config.max_image_pixels
    processor = cache.get(domain=domain)

    who = f"[{caller}] " if caller else ""
    print(f"{who}submitted job for {page_id!r} domain={domain or 'default'} fmt={fmt}", flush=True)

    def work():
        try:
            img = decode_image_path(spool_path, max_image_pixels)
        except ImageDecodeError as exc:
            raise JobInputError(str(exc)) from exc
        return processor.process(img, page_id=page_id, fmt=fmt,
                                 role_classifier=role_classifier, with_meta=True)

    result_ext = ".txt" if fmt == "txt" else ".xml"
    try:
        return store.submit(
            work,
            result_ext=result_ext,
            cleanup_fn=lambda: _unlink_spool(spool_path),
        )
    except JobStoreFull as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
            headers={"Retry-After": "5"},
        )


@router.get("/api/v1/models")
async def list_models(request: Request, caller_name: Optional[str] = Depends(_require_key)):
    cfg = request.app.state.config
    models_dir = _models.bundled_dir()
    onnx_files = sorted(p.name for p in models_dir.glob("*.onnx") if p.is_file())
    return {
        "defaults": {
            "ocr_model":    cfg.ocr_model,
            "layout_model": cfg.layout_model,
            "height_scale": cfg.height_scale,
        },
        "kramarky": {
            "ocr_model":    cfg.kramarky_ocr_model,
            "layout_model": cfg.kramarky_layout_model,
        },
        "handwritten": {
            "ocr_model":    cfg.handwritten_ocr_model,
            "layout_model": cfg.handwritten_layout_model,
        },
        "kurrent": {
            "ocr_model":    cfg.kurrent_ocr_model,
            "layout_model": cfg.kurrent_layout_model,
        },
        "available": {
            "ocr_models":    [f for f in onnx_files if "rec-" in f],
            "layout_models": [f for f in onnx_files if "dec-" in f],
        },
        "selectable_via_domain": ["default"] + sorted(ALLOWED_DOMAINS),
    }


def _reject_if_full(request: Request) -> None:
    if not request.app.state.store.has_capacity():
        raise HTTPException(
            status_code=503,
            detail=f"queue full (>= {request.app.state.config.max_queue})",
            headers={"Retry-After": "5"},
        )


async def _ingest_upload(request: Request, upload: UploadFile,
                         domain: Optional[str],
                         fmt: Optional[str], role_classifier: Optional[bool],
                         caller_name: Optional[str]) -> str:
    _reject_if_full(request)
    cfg = request.app.state.config
    spool_path = await _read_upload(upload, cfg.spool_dir)
    submitted = False
    try:
        job_id = _submit(
            request,
            spool_path,
            upload.filename or "page",
            domain,
            caller=caller_name,
            fmt=fmt,
            role_classifier=role_classifier,
        )
        submitted = True
        return job_id
    finally:
        if not submitted:
            _unlink_spool(spool_path)


@router.post("/api/v1/process")
async def process_image(
    request: Request,
    image: UploadFile = File(...),
    domain: Optional[str] = Form(None),
    fmt: Optional[str] = Form(None),
    role_classifier: Optional[bool] = Form(None),
    caller_name: Optional[str] = Depends(_require_key),
):
    job_id = await _ingest_upload(request, image, domain, fmt,
                                  role_classifier, caller_name)
    return {"job_id": job_id, "status": "queued"}


@router.get("/api/v1/status/{job_id}")
async def get_status(job_id: str, request: Request, caller_name: Optional[str] = Depends(_require_key)):
    store = request.app.state.store
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id":      job.id,
        "status":      job.status,
        "created_at":  job.created_at.isoformat(),
        "started_at":  job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "mean_conf":   job.mean_conf,
        "n_lines":     job.n_lines,
        "error":       job.error,
    }


def _result_response(store, job_id: str, which: Optional[str] = None) -> PlainTextResponse:
    if which is not None and which not in ALLOWED_WHICH:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown which '{which}'. Allowed: {sorted(ALLOWED_WHICH)}",
        )
    job = store.get(job_id)
    if job is not None:
        if job.status == "failed":
            raise HTTPException(status_code=job.error_status, detail=job.error or "Processing failed")
        if job.status not in ("done", "queued", "running"):
            raise HTTPException(status_code=404, detail="Job not found")
        if job.status != "done":
            raise HTTPException(status_code=202, detail=f"Job status: {job.status}")
    path = store.get_result_path(job_id, which)
    if path is None:
        raise HTTPException(status_code=404, detail="Result not found")
    content = path.read_text(encoding="utf-8")
    media_type = "text/plain; charset=utf-8" if path.suffix == ".txt" else "text/xml; charset=utf-8"
    return PlainTextResponse(content, media_type=media_type)


@router.get("/api/v1/result/{job_id}", response_class=PlainTextResponse)
async def get_result(job_id: str, request: Request,
                     which: Optional[str] = Query(None),
                     caller_name: Optional[str] = Depends(_require_key)):
    return _result_response(request.app.state.store, job_id, which)


@router.post("/upload")
async def upload_legacy(
    request: Request,
    file: UploadFile = File(...),
    domain: Optional[str] = Form(None),
    fmt: Optional[str] = Form(None),
    role_classifier: Optional[bool] = Form(None),
    caller_name: Optional[str] = Depends(_require_key),
):
    job_id = await _ingest_upload(request, file, domain, fmt,
                                  role_classifier, caller_name)
    return {"id": job_id}


@router.get("/status/{job_id}")
async def status_legacy(job_id: str, request: Request, caller_name: Optional[str] = Depends(_require_key)):
    store = request.app.state.store
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "id":    job.id,
        "state": "success" if job.status == "done" else job.status,
        "mean_conf": job.mean_conf,
        "n_lines":   job.n_lines,
        "error": job.error or "",
    }


@router.get("/download/{job_id}", response_class=PlainTextResponse)
async def download_legacy(job_id: str, request: Request,
                          which: Optional[str] = Query(None),
                          caller_name: Optional[str] = Depends(_require_key)):
    return _result_response(request.app.state.store, job_id, which)
