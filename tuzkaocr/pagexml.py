from datetime import datetime, timezone
from xml.etree import ElementTree as ET

from ._version import __version__
from .alto import _block_role, _xml_safe

PAGE_NS = "http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15"

_REGION_TYPE = {
    "heading": "heading",
    "header": "header",
    "footer": "footer",
    "page_number": "page-number",
}

_LANGUAGE_NAME = {
    "cs": "Czech",
    "de": "German",
    "en": "English",
    "sk": "Slovak",
    "pl": "Polish",
    "la": "Latin",
}


def _clip_point(x: object, y: object, page_w: int, page_h: int) -> tuple[int, int]:
    return (min(max(int(round(float(x))), 0), page_w - 1),
            min(max(int(round(float(y))), 0), page_h - 1))


def _points(pts: list, page_w: int, page_h: int) -> str | None:
    clipped = []
    for x, y in pts:
        point = _clip_point(x, y, page_w, page_h)
        if not clipped or clipped[-1] != point:
            clipped.append(point)
    if len(clipped) > 1 and clipped[0] == clipped[-1]:
        clipped.pop()
    if len(clipped) < 2:
        return None
    return " ".join(f"{x},{y}" for x, y in clipped)


def _rect_points(x: object, y: object, w: object, h: object,
                 page_w: int, page_h: int) -> str:
    x0, y0 = float(x), float(y)
    x1 = x0 + max(1.0, float(w))
    y1 = y0 + max(1.0, float(h))
    pts = _points([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], page_w, page_h)
    return pts or "0,0 1,1"


def _box_points(item: dict, page_w: int, page_h: int) -> str:
    return _rect_points(item["hpos"], item["vpos"], item["width"], item["height"],
                        page_w, page_h)


def _conf(value: object) -> str:
    return f"{min(1.0, max(0.0, float(value))):.4f}"


def _text_equiv(parent, text: str, conf: object = None) -> None:
    attrs = {} if conf is None else {"conf": _conf(conf)}
    equiv = ET.SubElement(parent, "TextEquiv", attrs)
    ET.SubElement(equiv, "Unicode").text = text


def _word_conf(word: dict):
    if word.get("conf") is not None:
        return word["conf"]
    char_conf = word.get("char_conf")
    return sum(char_conf) / len(char_conf) if char_conf else None


def _metadata_item(parent, name: str, value: str) -> None:
    ET.SubElement(parent, "MetadataItem", {
        "type": "processingStep", "name": name, "value": _xml_safe(value)})


def build_page_xml(page_id: str, img_h: int, img_w: int, blocks: list,
                   software_name: str = "tuzkaocr",
                   layout_name: str | None = None,
                   *,
                   source_file: str | None = None,
                   language: str | None = None) -> str:
    img_h = int(img_h)
    img_w = int(img_w)
    if img_w < 1 or img_h < 1:
        raise ValueError(f"PAGE page dimensions must be positive, got {img_w}x{img_h}")

    root = ET.Element("PcGts", {
        "xmlns": PAGE_NS,
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xsi:schemaLocation": f"{PAGE_NS} {PAGE_NS}/pagecontent.xsd",
    })

    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    metadata = ET.SubElement(root, "Metadata")
    ET.SubElement(metadata, "Creator").text = f"TuzkaOCR {__version__}"
    ET.SubElement(metadata, "Created").text = timestamp
    ET.SubElement(metadata, "LastChange").text = timestamp
    if layout_name:
        _metadata_item(metadata, "layout", layout_name)
    _metadata_item(metadata, "recognition", software_name)

    page_attrs = {
        "imageFilename": _xml_safe(source_file or page_id),
        "imageWidth": str(img_w),
        "imageHeight": str(img_h),
    }
    language_name = _LANGUAGE_NAME.get(language or "")
    if language_name:
        page_attrs["primaryLanguage"] = language_name
    page = ET.SubElement(root, "Page", page_attrs)

    regions = []
    for block in blocks or []:
        lines = []
        for line in block.get("lines") or []:
            words = [w for w in (line.get("words") or []) if _xml_safe(w.get("text", ""))]
            if words:
                lines.append((line, words))
        if lines:
            regions.append((block, lines))

    if regions:
        order = ET.SubElement(page, "ReadingOrder")
        group = ET.SubElement(order, "OrderedGroup", {"id": "ro_1"})
        for ri in range(len(regions)):
            ET.SubElement(group, "RegionRefIndexed",
                          {"index": str(ri), "regionRef": f"r{ri + 1:04d}"})

    for ri, (block, lines) in enumerate(regions):
        region_id = f"r{ri + 1:04d}"
        attrs = {"id": region_id, "custom": f"readingOrder {{index:{ri};}}",
                 "type": _REGION_TYPE.get(_block_role([l for l, _ in lines]) or "",
                                          "paragraph")}
        region = ET.SubElement(page, "TextRegion", attrs)

        region_points = _points(block["polygon"], img_w, img_h) if block.get("polygon") else None
        if region_points is None or region_points.count(" ") < 2:
            left = min(l["hpos"] for l, _ in lines)
            top = min(l["vpos"] for l, _ in lines)
            right = max(l["hpos"] + l["width"] for l, _ in lines)
            bottom = max(l["vpos"] + l["height"] for l, _ in lines)
            region_points = _rect_points(left, top, right - left, bottom - top, img_w, img_h)
        ET.SubElement(region, "Coords", {"points": region_points})

        region_text = []
        for li, (line, words) in enumerate(lines):
            line_id = f"{region_id}_l{li + 1:04d}"
            line_attrs = {"id": line_id, "custom": f"readingOrder {{index:{li};}}"}
            role = line.get("role")
            if role and role != "body":
                line_attrs["custom"] += f" structure {{type:{role};}}"
            text_line = ET.SubElement(region, "TextLine", line_attrs)

            line_points = _points(line["polygon"], img_w, img_h) if line.get("polygon") else None
            if line_points is None or line_points.count(" ") < 2:
                line_points = _box_points(line, img_w, img_h)
            ET.SubElement(text_line, "Coords", {"points": line_points})

            baseline = _points(line["baseline"], img_w, img_h) if line.get("baseline") else None
            if baseline:
                ET.SubElement(text_line, "Baseline", {"points": baseline})

            for wi, word in enumerate(words):
                word_el = ET.SubElement(text_line, "Word", {"id": f"{line_id}_w{wi + 1:04d}"})
                ET.SubElement(word_el, "Coords", {"points": _box_points(word, img_w, img_h)})
                _text_equiv(word_el, _xml_safe(word["text"]), _word_conf(word))

            text = _xml_safe(line.get("transcription")
                             or " ".join(w["text"] for w in words)).strip()
            _text_equiv(text_line, text, line.get("conf"))
            region_text.append(text)

        _text_equiv(region, "\n".join(region_text))

    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"
