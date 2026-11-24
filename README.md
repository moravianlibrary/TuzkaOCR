# TuzkaOCR

Lightweight OCR for scanned pages, optimized for CPU. TuzkaOCR detects the page layout and
text lines, recognizes each line, and returns ALTO XML or PAGE XML with word coordinates, or
plain text. It needs about 13 MB of models per domain and no GPU.

**Documentation: https://moravianlibrary.github.io/TuzkaOCR/** (sources in [`docs/`](docs/))

## Domains

| Domain | Material |
|---|---|
| `default` | Printed books, periodicals and general scans |
| `kramarky` | Kramarky broadsheet prints only |
| `handwritten` | Czech handwriting and German Kurrent / Sütterlin script |

## Quickstart

One line, no Python needed (installs [uv](https://docs.astral.sh/uv/) and the newest release):

```bash
curl -LsSf https://moravianlibrary.github.io/TuzkaOCR/install.sh | sh
```

Windows: `powershell -ExecutionPolicy ByPass -c "irm https://moravianlibrary.github.io/TuzkaOCR/install.ps1 | iex"`

Then `tuzkaocr app` opens a point-and-click app in your browser: pick a folder, tick pages,
read.

Or from a checkout:

```bash
git clone https://github.com/moravianlibrary/TuzkaOCR.git
cd TuzkaOCR
python3 -m venv .venv && source .venv/bin/activate
pip install .

tuzkaocr page.jpg --out page.alto.xml
tuzkaocr letter.jpg --domain handwritten --format txt --out letter.txt
tuzkaocr scans/ --batch --format multi --out-dir results/
```

Python 3.11–3.14 on Linux, Windows or Apple Silicon macOS. On Intel Macs, use Docker.
New to the command line? Follow the [step-by-step guide](docs/beginners.md).

## HTTP service

```bash
docker run -d -p 8000:8000 ghcr.io/moravianlibrary/tuzkaocr:latest
JOB=$(curl -s -F "image=@page.jpg" -F "fmt=alto" http://localhost:8000/api/v1/process | jq -r .job_id)
curl "http://localhost:8000/api/v1/status/$JOB"
curl -o page.alto.xml "http://localhost:8000/api/v1/result/$JOB"
```

Authentication is off by default; add `-e TUZKAOCR_API_KEY=<secret>` to `docker run` to
require an `X-API-Key` header (see [Setting an API key](docs/docker.md#setting-an-api-key)).

See [HTTP API](docs/api.md), [Docker](docs/docker.md) and
[Configuration](docs/configuration.md).

## License

Code: Apache License 2.0 (`LICENSE`, `NOTICE`). Models in `tuzkaocr/models/`:
CC BY-NC-SA 4.0 (`tuzkaocr/models/LICENSE`).
