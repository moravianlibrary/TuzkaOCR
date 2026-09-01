# TuzkaOCR

Lightweight OCR pipeline for scanned page and document images, optimized for CPU inference.
It detects page layout and text lines, runs line-level recognition, maps recognized words
back to source-image coordinates, and returns either ALTO XML with word bounding boxes or
plain text.

Around 12 MB of model artifacts per domain, no GPU required, and it runs anywhere ONNX
Runtime runs.

## What it does

- Page OCR for scanned books, archival material, and historical documents.
- Four material domains: printed, kramarky broadsheets, Czech handwriting, and German
  Kurrent/Sütterlin.
- ALTO XML output with page, block, line, and word coordinates, plus explicit model
  provenance.
- A command-line tool for single pages and batch directories.
- A FastAPI service with asynchronous job processing, and CPU and GPU container images.
- Optional API-key authentication, single-key or per-caller.

## How a page is processed

1. Load the image with OpenCV.
2. Detect regions, baselines, and line heights with the layout model.
3. Extract perspective-corrected line crops.
4. Recognize each line with the ONNX recognizer.
5. Assemble ALTO XML or plain text.

## Quickstart

```bash
git clone https://github.com/moravianlibrary/TuzkaOCR.git
cd TuzkaOCR
python3 -m venv .venv && source .venv/bin/activate
pip install .
tuzkaocr page.jpg --format txt --out page.txt
```

!!! tip "New to the command line?"
    [Step by step, no experience needed](beginners.md) walks through the same setup
    assuming no terminal experience, with the Windows and Mac differences spelled out.

[Full installation instructions](install.md){ .md-button .md-button--primary }
[CLI reference](cli.md){ .md-button }

## Where to go next

| If you want to | Read |
|---|---|
| Install and run it locally | [Installation](install.md) then [CLI](cli.md) |
| Do that without using a terminal before | [Step by step, no experience needed](beginners.md) |
| OCR pages over HTTP | [HTTP API](api.md) |
| Deploy it as a service | [Docker](docker.md) |
| Tune threads, memory, or limits | [Configuration](configuration.md) |
| Pick the right model for your material | [Models and domains](models.md) |
| Parse the output | [Output formats](output-formats.md) |
| Fix something that broke | [Troubleshooting](troubleshooting.md) |

## Licensing

The source code is licensed under the Apache License 2.0. The model artifacts in
`tuzkaocr/models/` are licensed separately under **CC BY-NC-SA 4.0** — non-commercial use
only. See `LICENSE`, `NOTICE`, and `tuzkaocr/models/LICENSE` in the repository.
