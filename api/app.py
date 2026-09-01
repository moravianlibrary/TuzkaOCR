from __future__ import annotations

import dataclasses
import tempfile
import threading
from contextlib import asynccontextmanager
from typing import Optional

import yaml
from fastapi import FastAPI
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from tuzkaocr.config import Config
from tuzkaocr.pipeline import PageProcessor
from tuzkaocr.jobs import JobStore

from api.routes import router, sweep_spool_files


def _validate_spool(spool_dir: str) -> None:
    try:
        with tempfile.NamedTemporaryFile(dir=spool_dir or None):
            pass
    except OSError as exc:
        raise RuntimeError(f"TUZKAOCR_SPOOL_DIR={spool_dir!r} is not writable: {exc}") from exc


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_bytes:
                    response = PlainTextResponse(
                        f"Request body exceeds {self.max_bytes} bytes",
                        status_code=413,
                    )
                    await response(scope, receive, send)
                    return
            except ValueError:
                pass

        seen = 0
        max_bytes = self.max_bytes
        overflowed = False
        response_sent = False

        async def limited_receive():
            nonlocal seen, overflowed, response_sent
            if overflowed:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body") or b"")
                if seen > max_bytes:
                    overflowed = True
                    while message.get("more_body"):
                        message = await receive()
                        if message["type"] != "http.request":
                            break
                    if not response_sent:
                        response_sent = True
                        response = PlainTextResponse(
                            f"Request body exceeds {max_bytes} bytes",
                            status_code=413,
                        )
                        await response(scope, receive, send)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message):
            if response_sent:
                return
            await send(message)

        await self.app(scope, limited_receive, guarded_send)


class ProcessorCache:
    DOMAIN_MODELS = {
        "kramarky":    ("kramarky_layout_model", "kramarky_ocr_model", 0.0, False),
        "handwritten": ("handwritten_layout_model", "handwritten_ocr_model", 0.3, True),
        "kurrent":     ("kurrent_layout_model", "kurrent_ocr_model", 0.3, True),
    }

    def __init__(self, default: PageProcessor, base_cfg: Config):
        self._default = default
        self._base_cfg = base_cfg
        self._by_domain: dict[str, PageProcessor] = {}
        self._lock = threading.Lock()

    def get(self, domain: Optional[str] = None) -> PageProcessor:
        if domain not in self.DOMAIN_MODELS:
            return self._default
        with self._lock:
            if domain not in self._by_domain:
                layout_field, ocr_field, ext, colsplit = self.DOMAIN_MODELS[domain]
                cfg = dataclasses.replace(
                    self._base_cfg,
                    ocr_model=getattr(self._base_cfg, ocr_field),
                    layout_model=getattr(self._base_cfg, layout_field),
                    crop_endpoint_ext=ext,
                    column_split=colsplit,
                )
                self._by_domain[domain] = PageProcessor(cfg)
            return self._by_domain[domain]


def _validate_auth(cfg: Config) -> None:
    if cfg.api_keys_file:
        try:
            with open(cfg.api_keys_file) as f:
                raw = yaml.safe_load(f) or {}
        except FileNotFoundError:
            raise RuntimeError(
                f"TUZKAOCR_API_KEYS_FILE={cfg.api_keys_file} not found. "
                "Create it (see api_keys.example.yaml) or unset the variable."
            )
        except yaml.YAMLError as exc:
            raise RuntimeError(f"TUZKAOCR_API_KEYS_FILE={cfg.api_keys_file} is not valid YAML: {exc}")
        if not isinstance(raw, dict) or not raw:
            raise RuntimeError(
                f"TUZKAOCR_API_KEYS_FILE={cfg.api_keys_file} is empty. "
                "Add at least one 'name: key' entry, or unset the variable to fall back "
                "to TUZKAOCR_API_KEY / disabled auth."
            )
        bad = [k for k, v in raw.items() if not isinstance(v, str) or not v.strip()]
        if bad:
            raise RuntimeError(
                f"TUZKAOCR_API_KEYS_FILE={cfg.api_keys_file} has empty/invalid keys for: {bad}"
            )
        print(f"[auth] multi-user, {len(raw)} key(s) loaded", flush=True)
    elif cfg.api_key:
        print("[auth] single-key", flush=True)
    else:
        print("[auth] DISABLED — only safe on a trusted network", flush=True)


def create_app(config: Config | None = None) -> FastAPI:
    cfg = config or Config()

    store: JobStore | None = None
    cleanup_timer: threading.Timer | None = None
    stopping = False

    def _run_periodic_cleanup():
        nonlocal cleanup_timer
        try:
            if store:
                removed = store.cleanup()
                if removed:
                    print(f"[cleanup] processed {removed} expired job(s)", flush=True)
        except Exception as exc:
            print(f"[cleanup] periodic cleanup failed: {exc}", flush=True)
        finally:
            if not stopping:
                cleanup_timer = threading.Timer(3600, _run_periodic_cleanup)
                cleanup_timer.daemon = True
                cleanup_timer.start()

    def _schedule_cleanup():
        nonlocal cleanup_timer
        cleanup_timer = threading.Timer(3600, _run_periodic_cleanup)
        cleanup_timer.daemon = True
        cleanup_timer.start()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal store, cleanup_timer, stopping
        stopping = False
        _validate_auth(cfg)
        _validate_spool(cfg.spool_dir)
        swept_spool = sweep_spool_files(cfg.spool_dir) if cfg.spool_dir else 0
        if swept_spool:
            print(f"[cleanup] removed {swept_spool} orphaned upload spool file(s) on startup", flush=True)
        print("Loading models...", flush=True)
        default_processor = PageProcessor(cfg)
        cache = ProcessorCache(default_processor, cfg)
        store = JobStore(
            cfg.results_path(),
            max_workers=cfg.page_workers,
            max_job_age_hours=cfg.max_job_age_hours,
            max_queue=cfg.max_queue,
        )
        app.state.cache = cache
        app.state.store = store
        app.state.config = cfg
        _schedule_cleanup()
        print("Ready.", flush=True)
        yield
        stopping = True
        if cleanup_timer:
            cleanup_timer.cancel()
        if store:
            queued, running = store.pending_count()
            if queued or running:
                print(f"[shutdown] draining {queued} queued + {running} running job(s)...", flush=True)
            store.shutdown()
            print("[shutdown] complete", flush=True)

    app = FastAPI(
        title="tuzkaocr",
        description="OCR pipeline for scanned page and document images — ALTO XML or text output",
        version="1.7.1",
        lifespan=lifespan,
    )

    app.add_middleware(BodySizeLimitMiddleware, max_bytes=cfg.max_upload_mb * 1024 * 1024)
    app.include_router(router)

    return app


app = create_app()
