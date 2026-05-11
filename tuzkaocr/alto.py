from datetime import datetime, timezone
from xml.dom import minidom
from xml.etree import ElementTree as ET


def build_alto(page_id: str, img_h: int, img_w: int, blocks: list,
               software_name: str = "tuzkaocr") -> str:
    alto = ET.Element("alto", {
        "xmlns": "http://www.loc.gov/standards/alto/ns-v4#",
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xsi:schemaLocation": (
            "http://www.loc.gov/standards/alto/ns-v4# "
            "http://www.loc.gov/standards/alto/v4/alto-4-4.xsd"
        ),
    })

    desc = ET.SubElement(alto, "Description")
    mu = ET.SubElement(desc, "MeasurementUnit")
    mu.text = "pixel"

    ocr_proc = ET.SubElement(desc, "OCRProcessing", {"ID": "IdOcr"})
    step = ET.SubElement(ocr_proc, "ocrProcessingStep")
    ET.SubElement(step, "processingDateTime").text = (
        datetime.now(timezone.utc).isoformat()
    )
    sw = ET.SubElement(step, "processingSoftware")
    ET.SubElement(sw, "softwareCreator").text = "tuzkaocr"
    ET.SubElement(sw, "softwareName").text = software_name

    layout = ET.SubElement(alto, "Layout")
    page = ET.SubElement(layout, "Page", {
        "ID": f"page_{page_id}",
        "WIDTH": str(img_w),
        "HEIGHT": str(img_h),
        "PHYSICAL_IMG_NR": "1",
    })
    ps = ET.SubElement(page, "PrintSpace", {
        "HPOS": "0", "VPOS": "0",
        "WIDTH": str(img_w), "HEIGHT": str(img_h),
    })

    for bi, block in enumerate(blocks):
        lines = block.get("lines")
        if not lines:
            continue
        bh = min(l["hpos"] for l in lines)
        bv = min(l["vpos"] for l in lines)
        br = max(l["hpos"] + l["width"] for l in lines)
        bb = max(l["vpos"] + l["height"] for l in lines)

        tb = ET.SubElement(ps, "TextBlock", {
            "ID": f"block_{bi}",
            "HPOS": str(bh), "VPOS": str(bv),
            "WIDTH": str(max(1, br - bh)), "HEIGHT": str(max(1, bb - bv)),
        })

        for li, line in enumerate(lines):
            tl = ET.SubElement(tb, "TextLine", {
                "ID": f"line_{bi}_{li}",
                "HPOS": str(line["hpos"]), "VPOS": str(line["vpos"]),
                "WIDTH": str(line["width"]), "HEIGHT": str(line["height"]),
            })
            for wi, (word, wh, wv, ww, wht) in enumerate(line["words"]):
                ET.SubElement(tl, "String", {
                    "ID": f"word_{bi}_{li}_{wi}",
                    "CONTENT": word,
                    "HPOS": str(max(0, wh)),
                    "VPOS": str(max(0, wv)),
                    "WIDTH": str(max(1, ww)),
                    "HEIGHT": str(max(1, wht)),
                })
                if wi < len(line["words"]) - 1:
                    ET.SubElement(tl, "SP")

    raw = ET.tostring(alto, encoding="unicode")
    return minidom.parseString(raw).toprettyxml(indent="  ")
