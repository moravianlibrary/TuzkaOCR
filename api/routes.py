from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import yaml
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Security, UploadFile, File
from fastapi.responses import PlainTextResponse
from fastapi.security.api_key import APIKeyHeader

from tuzkaocr.jobs import JobStoreFull

ALLOWED_DOMAINS = {"kramarky"}
ALLOWED_FMTS = {"alto", "txt"}
SPOOL_MAX_SIZE = 8 * 1024 * 1024

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


def _decode_image(data: bytes, max_pixels: int) -> np.ndarray:
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=422, detail="Cannot decode image")
    pixels = img.shape[0] * img.shape[1]
    if pixels > max_pixels:
        raise HTTPException(
            status_code=422,
            detail=f"Image too large: {pixels} pixels exceeds limit of {max_pixels}",
        )
    return img


def _validate_domain(domain: Optional[str]) -> Optional[str]:
    if domain in (None, ""):
        return None
    if domain not in ALLOWED_DOMAINS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown domain '{domain}'. Allowed: {sorted(ALLOWED_DOMAINS)}",
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


async def _read_upload(upload: UploadFile, spool_dir: Optional[str] = None) -> bytes:
    spool = tempfile.SpooledTemporaryFile(
        max_size=SPOOL_MAX_SIZE,
        dir=spool_dir or None,
    )
    try:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            spool.write(chunk)
        spool.seek(0)
        return spool.read()
    finally:
        spool.close()


def _submit(request: Request, img: np.ndarray, page_id: str,
            domain: Optional[str], height_scale: Optional[float],
            caller: Optional[str], fmt: Optional[str] = None) -> str:
    domain = _validate_domain(domain)
    fmt = _validate_fmt(fmt)
    cache = request.app.state.cache
    store = request.app.state.store
    processor = cache.get(domain=domain)

    who = f"[{caller}] " if caller else ""
    print(f"{who}submitted job for {page_id!r} domain={domain or 'default'} fmt={fmt}", flush=True)

    def work():
        return processor.process(img, page_id=page_id, fmt=fmt, height_scale=height_scale)

    result_ext = ".txt" if fmt == "txt" else ".xml"
    try:
        return store.submit(work, result_ext=result_ext)
    except JobStoreFull as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
            headers={"Retry-After": "5"},
        )


@router.get("/api/v1/models")
async def list_models(request: Request, caller_name: Optional[str] = Depends(_require_key)):
    cfg = request.app.state.config
    models_dir = Path(cfg.layout_model).parent
    onnx_files = sorted(str(p) for p in models_dir.glob("*.onnx") if p.is_file())
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
                         domain: Optional[str], height_scale: Optional[float],
                         fmt: Optional[str], caller_name: Optional[str]) -> str:
    _reject_if_full(request)
    cfg = request.app.state.config
    data = await _read_upload(upload, cfg.spool_dir)
    img = _decode_image(data, cfg.max_image_pixels)
    return _submit(request, img, upload.filename or "page",
                   domain, height_scale, caller=caller_name, fmt=fmt)


@router.post("/api/v1/process")
async def process_image(
    request: Request,
    image: UploadFile = File(...),
    domain: Optional[str] = Form(None),
    height_scale: Optional[float] = Form(None),
    fmt: Optional[str] = Form(None),
    caller_name: Optional[str] = Depends(_require_key),
):
    job_id = await _ingest_upload(request, image, domain, height_scale, fmt, caller_name)
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
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "error":       job.error,
    }


def _result_response(store, job_id: str) -> PlainTextResponse:
    job = store.get(job_id)
    if job is not None:
        if job.status == "failed":
            raise HTTPException(status_code=500, detail=job.error or "Processing failed")
        if job.status not in ("done", "queued", "running"):
            raise HTTPException(status_code=404, detail="Job not found")
        if job.status != "done":
            raise HTTPException(status_code=202, detail=f"Job status: {job.status}")
    path = store.get_result_path(job_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Result not found")
    content = path.read_text(encoding="utf-8")
    media_type = "text/plain; charset=utf-8" if path.suffix == ".txt" else "text/xml; charset=utf-8"
    return PlainTextResponse(content, media_type=media_type)


@router.get("/api/v1/result/{job_id}", response_class=PlainTextResponse)
async def get_result(job_id: str, request: Request, caller_name: Optional[str] = Depends(_require_key)):
    return _result_response(request.app.state.store, job_id)


@router.post("/upload")
async def upload_legacy(
    request: Request,
    file: UploadFile = File(...),
    domain: Optional[str] = Form(None),
    height_scale: Optional[float] = Form(None),
    fmt: Optional[str] = Form(None),
    caller_name: Optional[str] = Depends(_require_key),
):
    job_id = await _ingest_upload(request, file, domain, height_scale, fmt, caller_name)
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
        "error": job.error or "",
    }


@router.get("/download/{job_id}", response_class=PlainTextResponse)
async def download_legacy(job_id: str, request: Request, caller_name: Optional[str] = Depends(_require_key)):
    return _result_response(request.app.state.store, job_id)
