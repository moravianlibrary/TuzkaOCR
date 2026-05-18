from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(Path(".env"), override=False)
    load_dotenv(Path(__file__).parent.parent / "tuzkaocr.env", override=False)


_load_dotenv()


def _env(key: str, default):
    val = os.environ.get(f"TUZKAOCR_{key.upper()}")
    if val is None:
        return default
    t = type(default)
    if t is bool:
        return val.lower() in ("1", "true", "yes")
    return t(val)


@dataclass
class Config:
    layout_model: str = field(default_factory=lambda: _env("LAYOUT_MODEL", "dec-A-v3.onnx"))
    ocr_model:    str = field(default_factory=lambda: _env("OCR_MODEL",    "rec-E-v4.int8.onnx"))
    vocab:        str = field(default_factory=lambda: _env("VOCAB",        "vocab.json"))

    kramarky_layout_model: str = field(default_factory=lambda: _env("KRAMARKY_LAYOUT_MODEL", "dec-A-v3k5.onnx"))
    kramarky_ocr_model:    str = field(default_factory=lambda: _env("KRAMARKY_OCR_MODEL",    "rec-E-v4k7.int8.onnx"))

    device:       str   = field(default_factory=lambda: _env("DEVICE",       "cpu"))
    ocr_threads:  int   = field(default_factory=lambda: _env("OCR_THREADS",  4))
    line_workers: int   = field(default_factory=lambda: _env("LINE_WORKERS", 4))
    page_workers: int   = field(default_factory=lambda: _env("PAGE_WORKERS", 2))

    height_scale: float = field(default_factory=lambda: _env("HEIGHT_SCALE", 1.0))
    h_dilate:     int   = field(default_factory=lambda: _env("H_DILATE",     0))
    max_width:    int   = field(default_factory=lambda: _env("MAX_WIDTH",    1600))

    results_dir:        str = field(default_factory=lambda: _env("RESULTS_DIR",        "results"))
    max_job_age_hours:  int = field(default_factory=lambda: _env("MAX_JOB_AGE_HOURS",  24))

    max_upload_mb:      int = field(default_factory=lambda: _env("MAX_UPLOAD_MB",      256))
    max_image_pixels:   int = field(default_factory=lambda: _env("MAX_IMAGE_PIXELS",   300_000_000))
    max_queue:          int = field(default_factory=lambda: _env("MAX_QUEUE",          16))

    api_keys_file:      str = field(default_factory=lambda: _env("API_KEYS_FILE",      ""))
    api_key:            str = field(default_factory=lambda: _env("API_KEY",            ""))

    spool_dir:          str = field(default_factory=lambda: _env("SPOOL_DIR",          ""))

    _ALLOWED_DEVICES = ("cpu", "cuda", "auto")

    def __post_init__(self) -> None:
        errors: list[str] = []

        def _pos_int(name: str, val: int, *, allow_zero: bool = False) -> None:
            ok = val >= 0 if allow_zero else val > 0
            if not ok:
                errors.append(f"TUZKAOCR_{name.upper()} must be {'>=0' if allow_zero else '>0'}, got {val}")

        _pos_int("ocr_threads",       self.ocr_threads)
        _pos_int("line_workers",      self.line_workers)
        _pos_int("page_workers",      self.page_workers)
        _pos_int("max_width",         self.max_width)
        _pos_int("max_queue",         self.max_queue)
        _pos_int("max_upload_mb",     self.max_upload_mb)
        _pos_int("max_image_pixels",  self.max_image_pixels)
        _pos_int("max_job_age_hours", self.max_job_age_hours)
        _pos_int("h_dilate",          self.h_dilate, allow_zero=True)

        if self.device not in self._ALLOWED_DEVICES:
            errors.append(
                f"TUZKAOCR_DEVICE must be one of {self._ALLOWED_DEVICES}, got {self.device!r}"
            )
        if not (0.1 <= self.height_scale <= 10.0):
            errors.append(
                f"TUZKAOCR_HEIGHT_SCALE must be in [0.1, 10.0], got {self.height_scale}"
            )

        if self.spool_dir:
            p = Path(self.spool_dir)
            if not p.is_dir():
                errors.append(f"TUZKAOCR_SPOOL_DIR={self.spool_dir!r} is not an existing directory")

        if errors:
            raise RuntimeError("Invalid configuration:\n  - " + "\n  - ".join(errors))

    def resolve_device(self) -> str:
        if self.device == "auto":
            try:
                import onnxruntime as ort
                return "cuda" if "CUDAExecutionProvider" in ort.get_available_providers() else "cpu"
            except ImportError:
                return "cpu"
        return self.device

    def results_path(self) -> Path:
        p = Path(self.results_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p
