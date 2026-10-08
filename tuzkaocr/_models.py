from __future__ import annotations

from importlib.resources import files
from pathlib import Path


_BUNDLED_DIR = Path(str(files("tuzkaocr.models")))
_LEGACY_SUFFIXES = (".int8.onnx", ".fp32.onnx", ".fp16.onnx")


def bundled_dir() -> Path:
    return _BUNDLED_DIR


def display_name(path: str | Path) -> str:
    stem = Path(path).stem
    for suffix in (".int8", ".fp32", ".fp16"):
        if stem.endswith(suffix):
            return stem[:-len(suffix)]
    return stem


def resolve(value: str) -> Path:
    p = Path(value).expanduser()
    if p.is_file():
        return p.resolve()
    candidate = _BUNDLED_DIR / p.name
    if candidate.is_file():
        return candidate
    for suffix in _LEGACY_SUFFIXES:
        if p.name.endswith(suffix):
            legacy = _BUNDLED_DIR / (p.name[:-len(suffix)] + ".onnx")
            if legacy.is_file():
                return legacy
    raise FileNotFoundError(
        f"Model {value!r} not found on disk and not bundled in tuzkaocr.models "
        f"(bundled: {sorted(f.name for f in _BUNDLED_DIR.iterdir() if f.is_file())})"
    )
