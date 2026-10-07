import re
import statistics
import unicodedata
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

from ._version import __version__

HYPHEN_CHARS = "-\u2010\u2011\u00ad\u00ac=\u2e17"

PROFILES = ("basic", "ndk")

_ID_SAFE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
_ID_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]+")
_XML_ILLEGAL = re.compile(
    "[^\t\n\r\u0020-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]"
)
_XML_BREAKS = re.compile(r"[\t\r\n]+")
_TRAILING_ORDINAL = re.compile(r"\d+$")

MAX_ORDINAL_DIGITS = 5

_ALIGN_STYLE_ID = {
    "Left": "PS_Left",
    "Right": "PS_Right",
    "Center": "PS_Center",
    "Block": "PS_Block",
}

_TOP_ROLES = ("header",)
_BOTTOM_ROLES = ("footer", "page_number")


def sanitize_xml_id(value: object, prefix: str = "id") -> str:
    candidate = f"{prefix}_{value}"
    if _ID_SAFE.fullmatch(candidate):
        return candidate
    folded = unicodedata.normalize("NFKD", candidate).encode("ascii", "ignore").decode("ascii")
    sanitized = _ID_UNSAFE.sub("_", folded).strip(".-") or f"{prefix}_value"
    if not sanitized[0].isalpha() and sanitized[0] != "_":
        sanitized = f"{prefix}_{sanitized}"
    return sanitized


def physical_page_number(source_name: object) -> int | None:
    stem = str(source_name or "").replace("\\", "/").rsplit("/", 1)[-1]
    stem = stem.rsplit(".", 1)[0] if "." in stem else stem
    match = _TRAILING_ORDINAL.search(stem)
    if match is None or len(match.group()) > MAX_ORDINAL_DIGITS:
        return None
    value = int(match.group())
    return value if value >= 1 else None


def _xml_safe(value: object) -> str:
    return _XML_BREAKS.sub(" ", _XML_ILLEGAL.sub("", str(value)))


def _clip_rect(x: object, y: object, width: object, height: object,
               page_w: int, page_h: int, min_size: int = 1) -> tuple[int, int, int, int]:
    x0 = int(float(x))
    y0 = int(float(y))
    x1 = x0 + max(min_size, int(float(width)))
    y1 = y0 + max(min_size, int(float(height)))
    left = min(max(x0, 0), page_w - min_size)
    top = min(max(y0, 0), page_h - min_size)
    right = min(max(x1, left + min_size), page_w)
    bottom = min(max(y1, top + min_size), page_h)
    return left, top, right - left, bottom - top


class _Ids:
    def __init__(self, ndk: bool, page_prefix: str):
        self.ndk = ndk
        self.prefix = page_prefix
        self._tb = self._tl = self._st = self._sp = 0

    def block(self, bi: int) -> str:
        self._tb += 1
        return f"{self.prefix}_TB{self._tb:04d}" if self.ndk else f"block_{bi}"

    def line(self, bi: int, li: int) -> str:
        self._tl += 1
        return f"{self.prefix}_TL{self._tl:04d}" if self.ndk else f"line_{bi}_{li}"

    def string(self, bi: int, li: int, wi: int) -> str:
        self._st += 1
        return f"{self.prefix}_ST{self._st:04d}" if self.ndk else f"word_{bi}_{li}_{wi}"

    def space(self) -> str:
        self._sp += 1
        return f"{self.prefix}_SP{self._sp:04d}"


def _normalize_word(raw: object, page_w: int, page_h: int) -> dict:
    if isinstance(raw, dict):
        text = raw.get("text", "")
        box = (raw.get("hpos"), raw.get("vpos"), raw.get("width"), raw.get("height"))
        conf = raw.get("conf")
        char_conf = raw.get("char_conf")
        stem_box = raw.get("stem_box")
        hyp_box = raw.get("hyp_box")
    else:
        text = raw[0]
        box = tuple(raw[1:5])
        conf = char_conf = stem_box = hyp_box = None
    text = _xml_safe(text)
    char_conf = [float(p) for p in char_conf] if char_conf else None
    if char_conf is not None and len(char_conf) != len(text):
        char_conf = None
    return {
        "text": text,
        "box": _clip_rect(*box, page_w, page_h),
        "conf": None if conf is None else float(conf),
        "char_conf": char_conf,
        "stem_box": _clip_rect(*stem_box, page_w, page_h) if stem_box else None,
        "hyp_box": _clip_rect(*hyp_box, page_w, page_h) if hyp_box else None,
    }


def _block_role(lines: list) -> str | None:
    counts: dict[str, int] = {}
    for line in lines:
        role = line.get("role") or "body"
        counts[role] = counts.get(role, 0) + 1
    dominant = max(sorted(counts), key=counts.get)
    return None if dominant == "body" else dominant


def _normalize_blocks(blocks: list, page_w: int, page_h: int) -> list[dict]:
    normalized = []
    for index, block in enumerate(blocks or []):
        lines = []
        for line in block.get("lines") or []:
            words = [_normalize_word(word, page_w, page_h)
                     for word in (line.get("words") or [])]
            words = [word for word in words if word["text"]]
            if not words:
                continue
            hpos, vpos, width, height = _clip_rect(
                line["hpos"], line["vpos"], line["width"], line["height"], page_w, page_h)
            lines.append({
                "hpos": hpos, "vpos": vpos, "width": width, "height": height,
                "role": line.get("role"),
                "conf": line.get("conf"),
                "words": words,
            })
        if not lines:
            continue
        left = min(line["hpos"] for line in lines)
        top = min(line["vpos"] for line in lines)
        right = max(line["hpos"] + line["width"] for line in lines)
        bottom = max(line["vpos"] + line["height"] for line in lines)
        polygon = block.get("polygon")
        normalized.append({
            "index": index,
            "lines": lines,
            "hpos": left, "vpos": top,
            "width": max(1, right - left), "height": max(1, bottom - top),
            "role": _block_role(lines),
            "polygon": [(min(max(int(x), 0), page_w), min(max(int(y), 0), page_h))
                        for x, y in polygon] if polygon else None,
        })
    return normalized


def _partition_page(blocks: list, page_w: int, page_h: int) -> tuple:
    if not blocks:
        return (0, 0, page_w, page_h), [], [], []

    role_aware = any(block["role"] for block in blocks)
    top = {i for i, b in enumerate(blocks) if role_aware and b["role"] in _TOP_ROLES}
    bottom = {i for i, b in enumerate(blocks) if role_aware and b["role"] in _BOTTOM_ROLES}
    body = [i for i in range(len(blocks)) if i not in top and i not in bottom]
    if not body:
        top, bottom = set(), set()
        body = list(range(len(blocks)))

    for _ in range(len(blocks) + 1):
        first = min(blocks[i]["vpos"] for i in body)
        last = max(blocks[i]["vpos"] + blocks[i]["height"] for i in body)
        demoted = [i for i in top if blocks[i]["vpos"] + blocks[i]["height"] > first]
        demoted += [i for i in bottom if blocks[i]["vpos"] < last]
        if not demoted:
            break
        for i in demoted:
            top.discard(i)
            bottom.discard(i)
            body.append(i)
        body.sort()

    px = min(blocks[i]["hpos"] for i in body)
    py = min(blocks[i]["vpos"] for i in body)
    pw = max(1, max(blocks[i]["hpos"] + blocks[i]["width"] for i in body) - px)
    ph = max(1, max(blocks[i]["vpos"] + blocks[i]["height"] for i in body) - py)
    return ((px, py, pw, ph),
            [blocks[i] for i in sorted(top)],
            [blocks[i] for i in sorted(bottom)],
            [blocks[i] for i in body])


def _line_pitch(block: dict) -> float | None:
    tops = sorted(line["vpos"] for line in block["lines"])
    gaps = [later - earlier for earlier, later in zip(tops, tops[1:]) if later > earlier]
    return statistics.median(gaps) if gaps else None


def _em_px(line: dict, pitch: float | None) -> float:
    height = float(line["height"])
    return min(height, pitch) if pitch else height


def _font_size(em_px: float, dpi: int) -> float:
    return max(1.0, em_px * 72.0 / float(max(1, dpi)))


def _font_bucket(em_px: float, dpi: int) -> int:
    return max(1, int(_font_size(em_px, dpi) + 0.5))


def _align_of(block: dict) -> str:
    lines = block["lines"]
    lefts = [line["hpos"] for line in lines]
    rights = [line["hpos"] + line["width"] for line in lines]
    if len(lines) < 2:
        return "Left"
    tol = max(2.0, 0.02 * (max(rights) - min(lefts)))
    left_edges = lefts[1:] if len(lines) >= 3 and lefts[0] > min(lefts[1:]) + tol else lefts
    right_edges = rights[:-1] if len(lines) >= 3 else rights
    flush_left = (max(left_edges) - min(left_edges)) <= tol
    flush_right = (max(right_edges) - min(right_edges)) <= tol
    if flush_left and flush_right:
        return "Block"
    if flush_left:
        return "Left"
    if flush_right:
        return "Right"
    centers = [(left + right) / 2.0 for left, right in zip(lefts, rights)]
    return "Center" if (max(centers) - min(centers)) <= tol else "Left"


def _collect_styles(blocks: list, dpi: int | None, font_family: str | None) -> dict:
    if not blocks:
        return {}

    buckets: dict[int, list[float]] = {}
    pitches = {id(block): _line_pitch(block) for block in blocks}
    if dpi:
        for block in blocks:
            pitch = pitches[id(block)]
            for line in block["lines"]:
                em = _em_px(line, pitch)
                buckets.setdefault(_font_bucket(em, dpi), []).append(_font_size(em, dpi))

    text_ids = {}
    sizes = {}
    for rank, bucket in enumerate(sorted(buckets, reverse=True), start=1):
        text_ids[bucket] = f"TS{rank}"
        sizes[bucket] = sum(buckets[bucket]) / len(buckets[bucket])

    return {
        "text_ids": text_ids,
        "sizes": sizes,
        "aligns": {id(block): _align_of(block) for block in blocks},
        "pitches": pitches,
        "family": font_family,
        "dpi": dpi,
    }


def _paragraph_style_id(styles: dict, block: dict) -> str:
    return _ALIGN_STYLE_ID[styles["aligns"][id(block)]]


def _line_style_id(styles: dict, line: dict, block: dict) -> str:
    if not styles["text_ids"]:
        return _paragraph_style_id(styles, block)
    em = _em_px(line, styles["pitches"][id(block)])
    return styles["text_ids"][_font_bucket(em, styles["dpi"])]


def _block_style_refs(styles: dict, block: dict) -> str:
    paragraph = _paragraph_style_id(styles, block)
    if not styles["text_ids"]:
        return paragraph
    counts: dict[int, int] = {}
    pitch = styles["pitches"][id(block)]
    for line in block["lines"]:
        bucket = _font_bucket(_em_px(line, pitch), styles["dpi"])
        counts[bucket] = counts.get(bucket, 0) + 1
    dominant = max(sorted(counts, reverse=True), key=counts.get)
    return f"{styles['text_ids'][dominant]} {paragraph}"


def _keep_hyphen(head: str, tail: str) -> bool:
    if head[-1].isdigit() or tail[0].isdigit():
        return True
    if tail[0].isupper():
        return True
    return any(char in HYPHEN_CHARS for char in head)


def _plan_hyphenation(block: dict) -> tuple[dict, dict]:
    substitutions: dict[tuple[int, int], tuple[str, str, str]] = {}
    hyphens: dict[int, str] = {}
    lines = block["lines"]
    candidates: dict[int, tuple[str, str, str]] = {}
    for li in range(len(lines) - 1):
        current, following = lines[li], lines[li + 1]
        last = current["words"][-1]["text"]
        if len(last) < 2 or last[-1] not in HYPHEN_CHARS:
            continue
        head = last[:-1]
        tail = following["words"][0]["text"]
        if not tail or tail[0] in HYPHEN_CHARS:
            continue
        if not any(char.isalpha() for char in head):
            continue
        height = max(1, current["height"])
        gap = following["vpos"] - current["vpos"]
        if not 0.5 * height <= gap <= 3.0 * height:
            continue
        joined = head + ("-" if _keep_hyphen(head, tail) else "") + tail
        candidates[li] = (head, tail, joined)

    unsupported = {
        li
        for li in candidates
        if li + 1 in candidates and len(lines[li + 1]["words"]) == 1
    }
    unsupported |= {li + 1 for li in unsupported}
    for li, (head, tail, joined) in candidates.items():
        if li in unsupported:
            continue
        current = lines[li]
        last = current["words"][-1]["text"]
        substitutions[(li, len(current["words"]) - 1)] = ("HypPart1", head, joined)
        substitutions[(li + 1, 0)] = ("HypPart2", tail, joined)
        hyphens[li] = last[-1]
    return substitutions, hyphens


def _cc_value(char_conf: list | None, content: str) -> str | None:
    if not char_conf or len(char_conf) != len(content):
        return None
    return "".join(str(min(9, max(0, int((1.0 - p) * 9.0 + 0.5)))) for p in char_conf)


def _wc_value(conf: float) -> str:
    return f"{min(1.0, max(0.0, float(conf))):.2f}"


def _emit_string(parent, word: dict, string_id: str, subs, ndk: bool,
                 language: str | None = None) -> None:
    content = word["text"]
    box = word["box"]
    char_conf = word["char_conf"]
    conf = word["conf"]
    subs_type = subs_content = None

    if subs is not None:
        subs_type, content, subs_content = subs
        if subs_type == "HypPart1":
            if word["stem_box"]:
                box = word["stem_box"]
            if char_conf:
                char_conf = char_conf[:-1]
                conf = sum(char_conf) / len(char_conf) if char_conf else conf

    attrs = {
        "ID": string_id,
        "CONTENT": content,
        "HPOS": str(box[0]), "VPOS": str(box[1]),
        "WIDTH": str(box[2]), "HEIGHT": str(box[3]),
    }
    if ndk:
        if conf is None and char_conf:
            conf = sum(char_conf) / len(char_conf)
        if conf is not None:
            attrs["WC"] = _wc_value(conf)
        cc = _cc_value(char_conf, content)
        if cc is not None:
            attrs["CC"] = cc
        if language:
            attrs["LANG"] = language
        if subs_type is not None:
            attrs["SUBS_TYPE"] = subs_type
            attrs["SUBS_CONTENT"] = subs_content
    ET.SubElement(parent, "String", attrs)


def _emit_text_block(parent, block: dict, bi: int, ctx: dict) -> None:
    ndk = ctx["ndk"]
    attrs = {"ID": ctx["ids"].block(bi)}
    if ndk and ctx["styles"]:
        attrs["STYLEREFS"] = _block_style_refs(ctx["styles"], block)
    attrs.update({
        "HPOS": str(block["hpos"]), "VPOS": str(block["vpos"]),
        "WIDTH": str(block["width"]), "HEIGHT": str(block["height"]),
    })
    if ndk and ctx["language"]:
        attrs["LANG"] = ctx["language"]
    tb = ET.SubElement(parent, "TextBlock", attrs)

    if ndk and block["polygon"]:
        shape = ET.SubElement(tb, "Shape")
        ET.SubElement(shape, "Polygon", {
            "POINTS": " ".join(f"{x},{y}" for x, y in block["polygon"])})

    substitutions, hyphens = _plan_hyphenation(block) if ndk else ({}, {})

    for li, line in enumerate(block["lines"]):
        line_attrs = {"ID": ctx["ids"].line(bi, li)}
        if ndk and ctx["styles"]:
            line_attrs["STYLEREFS"] = _line_style_id(ctx["styles"], line, block)
        line_attrs.update({
            "HPOS": str(line["hpos"]), "VPOS": str(line["vpos"]),
            "WIDTH": str(line["width"]), "HEIGHT": str(line["height"]),
        })
        if ndk and ctx["language"]:
            line_attrs["LANG"] = ctx["language"]
        role = line.get("role")
        if role and role in ctx["role_tag_id"]:
            line_attrs["TAGREFS"] = ctx["role_tag_id"][role]
        tl = ET.SubElement(tb, "TextLine", line_attrs)

        words = line["words"]
        for wi, word in enumerate(words):
            _emit_string(tl, word, ctx["ids"].string(bi, li, wi),
                         substitutions.get((li, wi)), ndk, ctx["language"])
            if wi == len(words) - 1:
                continue
            if not ndk:
                ET.SubElement(tl, "SP")
                continue
            left = word["box"][0] + word["box"][2]
            right = words[wi + 1]["box"][0]
            ET.SubElement(tl, "SP", {
                "ID": ctx["ids"].space(),
                "HPOS": str(min(max(left, 0), ctx["page_w"])),
                "VPOS": str(line["vpos"]),
                "WIDTH": str(max(0, right - left)),
            })

        if li in hyphens:
            hyp_attrs = {"CONTENT": hyphens[li]}
            hyp_box = words[-1]["hyp_box"]
            if hyp_box:
                hyp_attrs.update({
                    "HPOS": str(hyp_box[0]), "VPOS": str(hyp_box[1]),
                    "WIDTH": str(hyp_box[2]),
                })
            ET.SubElement(tl, "HYP", hyp_attrs)


def _emit_pre_operation(parent, timestamp: str, agency: str | None,
                        downsample: float) -> None:
    step = ET.SubElement(parent, "Processing", {"ID": "IdPreOperation"})
    ET.SubElement(step, "processingCategory").text = "preOperation"
    ET.SubElement(step, "processingDateTime").text = timestamp
    if agency:
        ET.SubElement(step, "processingAgency").text = _xml_safe(agency)
    ET.SubElement(step, "processingStepDescription").text = (
        "image downsampled for layout analysis")
    ET.SubElement(step, "processingStepSettings").text = (
        f"downsample factor {downsample:.2f}")
    software = ET.SubElement(step, "processingSoftware")
    ET.SubElement(software, "softwareCreator").text = "tuzkaocr"
    ET.SubElement(software, "softwareName").text = "TuzkaOCR"
    ET.SubElement(software, "softwareVersion").text = __version__


def _emit_processing(parent, step_id: str, description: str, model_name: str,
                     timestamp: str, agency: str | None) -> None:
    step = ET.SubElement(parent, "Processing", {"ID": step_id})
    ET.SubElement(step, "processingCategory").text = "contentGeneration"
    ET.SubElement(step, "processingDateTime").text = timestamp
    if agency:
        ET.SubElement(step, "processingAgency").text = _xml_safe(agency)
    ET.SubElement(step, "processingStepDescription").text = description
    software = ET.SubElement(step, "processingSoftware")
    ET.SubElement(software, "softwareCreator").text = "tuzkaocr"
    ET.SubElement(software, "softwareName").text = "TuzkaOCR"
    ET.SubElement(software, "softwareVersion").text = __version__
    ET.SubElement(software, "applicationDescription").text = (
        f"{description} model {_xml_safe(model_name)}")


def _emit_ocr_processing(parent, step_id: str, description: str, model_name: str,
                         timestamp: str) -> None:
    legacy = ET.SubElement(parent, "OCRProcessing", {"ID": step_id})
    step = ET.SubElement(legacy, "ocrProcessingStep")
    ET.SubElement(step, "processingDateTime").text = timestamp
    ET.SubElement(step, "processingStepDescription").text = description
    software = ET.SubElement(step, "processingSoftware")
    ET.SubElement(software, "softwareCreator").text = "tuzkaocr"
    ET.SubElement(software, "softwareName").text = model_name


def build_alto(page_id: str, img_h: int, img_w: int, blocks: list,
               software_name: str = "tuzkaocr",
               layout_name: str | None = None,
               *,
               profile: str = "ndk",
               source_file: str | None = None,
               source_identifier: str | None = None,
               page_confidence: float | None = None,
               physical_img_nr: int | None = None,
               layout_downsample: float | None = None,
               language: str | None = None,
               dpi: int | None = None,
               agency: str | None = None,
               font_family: str | None = None) -> str:
    if profile not in PROFILES:
        raise ValueError(f"ALTO profile must be one of {PROFILES}, got {profile!r}")
    if (physical_img_nr is not None
            and (isinstance(physical_img_nr, bool)
                 or not isinstance(physical_img_nr, int)
                 or physical_img_nr <= 0)):
        raise ValueError("physical_img_nr must be a positive integer")
    ndk = profile == "ndk"

    img_h = int(img_h)
    img_w = int(img_w)
    if img_w < 1 or img_h < 1:
        raise ValueError(f"ALTO page dimensions must be positive, got {img_w}x{img_h}")

    alto = ET.Element("alto", {
        "xmlns": "http://www.loc.gov/standards/alto/ns-v4#",
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xsi:schemaLocation": (
            "http://www.loc.gov/standards/alto/ns-v4# "
            "http://www.loc.gov/standards/alto/v4/alto-4-4.xsd"
        ),
        "SCHEMAVERSION": "4.4",
    })

    desc = ET.SubElement(alto, "Description")
    ET.SubElement(desc, "MeasurementUnit").text = "pixel"

    if ndk and (source_file or source_identifier):
        source = ET.SubElement(desc, "sourceImageInformation")
        if source_file:
            ET.SubElement(source, "fileName").text = _xml_safe(source_file)
        if source_identifier:
            ET.SubElement(source, "fileIdentifier").text = _xml_safe(source_identifier)

    now = datetime.now(timezone.utc)
    timestamp = now.replace(microsecond=0).isoformat() if ndk else now.isoformat()

    if ndk:
        if layout_downsample and abs(float(layout_downsample) - 1.0) > 1e-6:
            _emit_pre_operation(desc, timestamp, agency, float(layout_downsample))
        if layout_name:
            _emit_processing(desc, "IdLayout", "layout", layout_name, timestamp, agency)
        _emit_processing(desc, "IdRecognition", "recognition", software_name,
                         timestamp, agency)
    else:
        if layout_name:
            _emit_ocr_processing(desc, "IdLayout", "layout", layout_name, timestamp)
        _emit_ocr_processing(desc, "IdRecognition", "recognition", software_name, timestamp)

    normalized = _normalize_blocks(blocks, img_w, img_h)
    styles = _collect_styles(normalized, dpi, font_family) if ndk else {}

    if styles:
        styles_el = ET.SubElement(alto, "Styles")
        for bucket in sorted(styles["text_ids"], reverse=True):
            text_style = {"ID": styles["text_ids"][bucket]}
            if styles["family"]:
                text_style["FONTFAMILY"] = _xml_safe(styles["family"])
            text_style["FONTSIZE"] = f"{styles['sizes'][bucket]:.1f}"
            ET.SubElement(styles_el, "TextStyle", text_style)
        for align in sorted({styles["aligns"][id(block)] for block in normalized}):
            ET.SubElement(styles_el, "ParagraphStyle", {
                "ID": _ALIGN_STYLE_ID[align],
                "ALIGN": align,
            })

    used_roles = []
    for block in normalized:
        for line in block["lines"]:
            role = line.get("role")
            if role and role != "body" and role not in used_roles:
                used_roles.append(role)
    role_tag_id = {role: f"ROLE_{role}" for role in used_roles}
    if used_roles:
        tags = ET.SubElement(alto, "Tags")
        for role in used_roles:
            ET.SubElement(tags, "StructureTag", {"ID": role_tag_id[role], "LABEL": role})

    layout = ET.SubElement(alto, "Layout")
    page_attrs = {
        "ID": "P1" if ndk else sanitize_xml_id(page_id, "page"),
        "WIDTH": str(img_w),
        "HEIGHT": str(img_h),
        "PHYSICAL_IMG_NR": str(
            physical_img_nr
            if physical_img_nr is not None
            else ((physical_page_number(source_file) if ndk else None) or 1)
        ),
    }
    if ndk:
        if language:
            page_attrs["LANG"] = language
        if page_confidence is not None:
            confidence = min(1.0, max(0.0, float(page_confidence)))
            page_attrs["ACCURACY"] = f"{confidence * 100.0:.2f}"
            page_attrs["PC"] = f"{confidence:.4f}"
    page = ET.SubElement(layout, "Page", page_attrs)

    (px, py, pw, ph), top_blocks, bottom_blocks, body_blocks = _partition_page(
        normalized, img_w, img_h)

    ctx = {
        "ndk": ndk,
        "ids": _Ids(ndk, "P1"),
        "styles": styles,
        "language": language,
        "role_tag_id": role_tag_id,
        "page_w": img_w,
    }

    def emit_into(parent, members):
        for block in members:
            _emit_text_block(parent, block, block["index"], ctx)

    if ndk:
        margins = (
            ("TopMargin", "TM", _clip_rect(0, 0, img_w, py, img_w, img_h, 0), top_blocks),
            ("LeftMargin", "LM", _clip_rect(0, py, px, ph, img_w, img_h, 0), []),
            ("RightMargin", "RM",
             _clip_rect(px + pw, py, img_w - (px + pw), ph, img_w, img_h, 0), []),
            ("BottomMargin", "BM",
             _clip_rect(0, py + ph, img_w, img_h - (py + ph), img_w, img_h, 0), bottom_blocks),
        )
        for tag, code, rect, members in margins:
            element = ET.SubElement(page, tag, {
                "ID": f"P1_{code}0001",
                "HPOS": str(rect[0]), "VPOS": str(rect[1]),
                "WIDTH": str(rect[2]), "HEIGHT": str(rect[3]),
            })
            emit_into(element, members)

    space_attrs = {"ID": "P1_PS0001"} if ndk else {}
    space_attrs.update({
        "HPOS": str(px if ndk else 0), "VPOS": str(py if ndk else 0),
        "WIDTH": str(pw if ndk else img_w), "HEIGHT": str(ph if ndk else img_h),
    })
    print_space = ET.SubElement(page, "PrintSpace", space_attrs)
    emit_into(print_space, body_blocks if ndk else normalized)

    ET.indent(alto, space="  ")
    return '<?xml version="1.0" ?>\n' + ET.tostring(alto, encoding="unicode") + "\n"
