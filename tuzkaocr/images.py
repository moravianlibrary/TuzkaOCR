from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


class ImageDecodeError(ValueError):
    pass


_CM_PER_INCH = 2.54
_MM_PER_INCH = 25.4
_MIN_DPI = 1
_MIN_DECLARED_DPI = 100
_MAX_DPI = 20000

_TAG_X_RESOLUTION = 0x011A
_TAG_Y_RESOLUTION = 0x011B
_TAG_RESOLUTION_UNIT = 0x0128
_TYPE_SHORT = 3
_TYPE_RATIONAL = 5


def decode_image_path(path: str | Path, max_pixels: int | None = None) -> np.ndarray:
    image_path = Path(path)
    try:
        data = np.fromfile(image_path, dtype=np.uint8)
    except OSError as exc:
        raise ImageDecodeError(f"Cannot read image: {image_path}") from exc
    if data.size == 0:
        raise ImageDecodeError("Cannot decode image")
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise ImageDecodeError("Cannot decode image")
    pixels = int(img.shape[0]) * int(img.shape[1])
    if max_pixels is not None and pixels > max_pixels:
        raise ImageDecodeError(f"Image too large: {pixels} pixels exceeds limit of {max_pixels}")
    return img


def _plausible(value: float | None, minimum: int = _MIN_DPI) -> int | None:
    if value is None or value <= 0:
        return None
    dpi = int(round(value))
    return dpi if minimum <= dpi <= _MAX_DPI else None


def _tiff_dpi(handle, base: int) -> int | None:
    handle.seek(base)
    header = handle.read(8)
    if len(header) < 8:
        return None
    if header[:2] == b"II":
        order = "little"
    elif header[:2] == b"MM":
        order = "big"
    else:
        return None

    def number(raw: bytes) -> int:
        return int.from_bytes(raw, order)

    handle.seek(base + number(header[4:8]))
    count_raw = handle.read(2)
    if len(count_raw) < 2:
        return None
    entries = handle.read(number(count_raw) * 12)

    unit = 2
    resolutions: dict[int, float] = {}
    pointers: dict[int, int] = {}
    for offset in range(0, len(entries) - 11, 12):
        entry = entries[offset:offset + 12]
        tag = number(entry[0:2])
        kind = number(entry[2:4])
        if tag == _TAG_RESOLUTION_UNIT and kind == _TYPE_SHORT:
            unit = number(entry[8:10])
        elif tag in (_TAG_X_RESOLUTION, _TAG_Y_RESOLUTION) and kind == _TYPE_RATIONAL:
            pointers[tag] = number(entry[8:12])

    if unit == 1:
        return None
    for tag, pointer in pointers.items():
        handle.seek(base + pointer)
        rational = handle.read(8)
        if len(rational) < 8:
            continue
        denominator = number(rational[4:8])
        if denominator:
            resolutions[tag] = number(rational[0:4]) / denominator

    value = resolutions.get(_TAG_X_RESOLUTION) or resolutions.get(_TAG_Y_RESOLUTION)
    if value is None:
        return None
    return _plausible(value if unit == 2 else value * _CM_PER_INCH)


def _jpeg_dpi(handle) -> int | None:
    handle.seek(2)
    jfif: int | None = None
    while True:
        marker = handle.read(2)
        if len(marker) < 2 or marker[0] != 0xFF:
            return jfif
        code = marker[1]
        if code == 0xDA or code == 0xD9:
            return jfif
        if code == 0x01 or 0xD0 <= code <= 0xD8:
            continue
        length_raw = handle.read(2)
        if len(length_raw) < 2:
            return jfif
        length = int.from_bytes(length_raw, "big") - 2
        if length < 0:
            return jfif
        payload_start = handle.tell()
        header = handle.read(min(length, 16))
        if code == 0xE0 and header[:5] == b"JFIF\x00" and len(header) >= 12:
            unit = header[7]
            density = int.from_bytes(header[8:10], "big")
            if unit == 1:
                jfif = _plausible(density)
            elif unit == 2:
                jfif = _plausible(density * _CM_PER_INCH)
        elif code == 0xE1 and header[:6] == b"Exif\x00\x00":
            exif = _tiff_dpi(handle, payload_start + 6)
            if exif is not None:
                return exif
        handle.seek(payload_start + length)


def _png_dpi(handle) -> int | None:
    handle.seek(8)
    while True:
        header = handle.read(8)
        if len(header) < 8:
            return None
        length = int.from_bytes(header[0:4], "big")
        kind = header[4:8]
        if kind == b"pHYs":
            chunk = handle.read(min(length, 9))
            if len(chunk) < 9 or chunk[8] != 1:
                return None
            return _plausible(int.from_bytes(chunk[0:4], "big") * 0.0254)
        if kind in (b"IDAT", b"IEND"):
            return None
        handle.seek(length + 4, 1)


def dpi_from_page_width(pixel_width: int, page_width_mm: float) -> int | None:
    if pixel_width < 1 or page_width_mm <= 0:
        return None
    return _plausible(pixel_width / (page_width_mm / _MM_PER_INCH))


def _declared_dpi(path: str | Path) -> int | None:
    with open(path, "rb") as handle:
        signature = handle.read(8)
        if signature[:2] == b"\xff\xd8":
            return _jpeg_dpi(handle)
        if signature == b"\x89PNG\r\n\x1a\n":
            return _png_dpi(handle)
        if signature[:4] in (b"II*\x00", b"MM\x00*"):
            return _tiff_dpi(handle, 0)
    return None


def read_image_dpi(path: str | Path) -> int | None:
    try:
        return _plausible(_declared_dpi(path), _MIN_DECLARED_DPI)
    except (OSError, ValueError):
        return None
