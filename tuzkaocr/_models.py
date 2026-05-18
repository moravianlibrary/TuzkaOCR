from __future__ import annotations

from importlib.resources import files
from pathlib import Path


_BUNDLED_DIR = Path(str(files("tuzkaocr.models")))


def bundled_dir() -> Path:
    return _BUNDLED_DIR


def resolve(value: str) -> Path:
    p = Path(value).expanduser()
    if p.is_file():
        return p.resolve()
    candidate = _BUNDLED_DIR / p.name
    if candidate.is_file():
        return candidate
    raise FileNotFoundError(
        f"Model {value!r} not found on disk and not bundled in tuzkaocr.models "
        f"(bundled: {sorted(f.name for f in _BUNDLED_DIR.iterdir() if f.is_file())})"
    )
