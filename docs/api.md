# HTTP API

The service accepts an image, processes it asynchronously, and serves the result as ALTO
XML or plain text. Model selection is server-side: a client picks a *domain*, never a model
file.

## Starting the server

=== "Docker (recommended)"

    ```bash
    docker compose up --build -d cpu
    curl http://localhost:8000/healthz
    ```

    See [Docker](docker.md) for ports, volumes, and the GPU profile.

=== "Directly"

    ```bash
    uvicorn api.app:app --host 0.0.0.0 --port 8000
    ```

    ```
    [auth] DISABLED — only safe on a trusted network
    Loading models...
    Ready.
    ```

Interactive OpenAPI documentation is served at `/docs`, and the schema at
`/openapi.json`.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/healthz` | Liveness check; never authenticated |
| `POST` | `/api/v1/process` | Submit an image, receive a job ID |
| `GET` | `/api/v1/status/{job_id}` | Job state, line count, mean confidence |
| `GET` | `/api/v1/result/{job_id}` | Download the finished output |
| `GET` | `/api/v1/models` | Configured and bundled models |

Legacy-compatible aliases exist for older clients — see [below](#legacy-endpoints).

## Submitting a page

`POST /api/v1/process`, as `multipart/form-data`:

| Field | Type | Default | Values |
|---|---|---|---|
| `image` | file | *required* | JPEG, PNG, or TIFF |
| `domain` | string | printed | `default`, `print`, `kramarky`, `handwritten`, `kurrent` |
| `fmt` | string | `alto` | `alto`, `txt`, `multi` |
| `role_classifier` | bool | server default | `true` / `false` |

```bash
curl -F "image=@page.jpg" http://localhost:8000/api/v1/process
```

```json
{"job_id": "3f2b1c8e-5d47-4a19-9c33-8e1f0a7b6d24", "status": "queued"}
```

An empty `domain`, or `default` / `print` / `printed`, all select the printed models. An
unrecognized `domain` or `fmt` is rejected with **400** before the job is created.

## Polling and downloading

```bash
JOB=$(curl -s -F "image=@page.jpg" -F "domain=kramarky" -F "fmt=txt" \
        http://localhost:8000/api/v1/process | jq -r .job_id)

curl -s "http://localhost:8000/api/v1/status/$JOB"
```

```json
{
  "job_id": "3f2b1c8e-5d47-4a19-9c33-8e1f0a7b6d24",
  "status": "done",
  "created_at": "2026-08-31T09:14:02.118904+00:00",
  "started_at": "2026-08-31T09:14:02.121550+00:00",
  "finished_at": "2026-08-31T09:14:04.902733+00:00",
  "mean_conf": 0.9421,
  "n_lines": 37,
  "error": null
}
```

`status` is one of `queued`, `running`, `done`, or `failed`. `mean_conf` is the mean
per-line recognition confidence and is a useful triage signal for bulk ingest — low values
flag pages worth re-scanning.

```bash
curl -o result.txt "http://localhost:8000/api/v1/result/$JOB"
```

The result endpoint doubles as a wait: it returns **202** while the job is `queued` or
`running`, so a client can poll it directly instead of polling status.

### Getting both formats

With `fmt=multi` the server produces ALTO and text from one OCR pass, and `?which=`
chooses which to download. It defaults to `alto`.

```bash
JOB=$(curl -s -F "image=@page.jpg" -F "fmt=multi" \
        http://localhost:8000/api/v1/process | jq -r .job_id)

curl -o result.alto.xml "http://localhost:8000/api/v1/result/$JOB"
curl -o result.txt      "http://localhost:8000/api/v1/result/$JOB?which=txt"
```

Responses carry `text/xml; charset=utf-8` or `text/plain; charset=utf-8` accordingly.

## Status codes

| Code | When |
|---|---|
| `200` | Result returned |
| `202` | Job accepted but still `queued` or `running` |
| `400` | Unknown `domain`, `fmt`, or `which` |
| `401` | Missing or invalid API key, when authentication is enabled |
| `404` | Unknown job ID, or no result file for it |
| `413` | Request body exceeds `TUZKAOCR_MAX_UPLOAD_MB` |
| `422` | The image could not be decoded, or exceeds `TUZKAOCR_MAX_IMAGE_PIXELS` |
| `500` | Processing failed for another reason; `error` carries the message |
| `503` | Queue is full; a `Retry-After: 5` header is included |

Oversize uploads are rejected cleanly whether or not the request declares a
`Content-Length`, so streaming clients get a **413** rather than a broken connection.

!!! note "Decode failures surface late"
    An upload is accepted before the image is decoded, so a corrupt or over-large image
    becomes a **failed job** rather than a rejected request. The failure appears as
    `status: failed` with a message, and the result endpoint then answers **422**.

## Backpressure

`TUZKAOCR_MAX_QUEUE` (default 16) caps queued plus running jobs. Submitting past that
returns **503** with `Retry-After: 5`; the check happens before the upload is spooled, so a
full queue costs the client nothing but the round trip.

Honour the header — a client that retries immediately will simply be refused again.
Concurrency is set by `TUZKAOCR_PAGE_WORKERS`, not by the queue size.

## Job lifetime and retention

Jobs are tracked in memory; results are files under `TUZKAOCR_RESULTS_DIR`. Both are
removed once a job is older than `TUZKAOCR_MAX_JOB_AGE_HOURS` (default 24). The sweep runs
at startup and hourly, and also collects orphaned result files left by earlier server
lifetimes.

Two consequences worth designing around:

- **Fetch results within the retention window.** After it passes, the job and its files are
  gone.
- **A restart forgets job metadata but keeps the files.** `status` answers **404** for a job
  submitted before the restart, while `result` still serves it — the result endpoint falls
  back to looking up the file by job ID on disk. Store the job IDs you care about
  client-side.

## Authentication

Off by default, which is only safe on a trusted network. Two modes, both using the
`X-API-Key` header.

=== "Single shared key"

    ```bash
    TUZKAOCR_API_KEY=your-secret-key
    ```

    ```bash
    curl -H "X-API-Key: your-secret-key" http://localhost:8000/api/v1/models
    ```

=== "Per-caller keys"

    For per-caller identity in the server log. Copy the template, fill it in, and point the
    server at it:

    ```bash
    cp api_keys.example.yaml api_keys.yaml
    ```

    ```yaml
    user-name: generated-secret-key
    integration-name: another-generated-secret-key
    ```

    ```bash
    TUZKAOCR_API_KEYS_FILE=/app/api_keys.yaml
    ```

    The file is re-read every 10 seconds, so keys rotate without a restart. It takes
    precedence over `TUZKAOCR_API_KEY`. Generate keys with:

    ```bash
    python -c "import secrets; print(secrets.token_urlsafe(32))"
    ```

`/healthz` is deliberately left unauthenticated so container health checks and load
balancers work. Every other endpoint requires the key once either mode is enabled, and
startup fails with a clear message if the key file is missing, empty, or unparseable.

## Listing models

```bash
curl -s http://localhost:8000/api/v1/models
```

```json
{
  "defaults":    {"ocr_model": "rec-E-v5.int8.onnx",  "layout_model": "dec-B-v2.onnx", "height_scale": 1.0},
  "kramarky":    {"ocr_model": "rec-E-v4k7.int8.onnx", "layout_model": "dec-B-v1k.onnx"},
  "handwritten": {"ocr_model": "rec-H-v6.int8.onnx",  "layout_model": "dec-B-v2h.onnx"},
  "kurrent":     {"ocr_model": "rec-H-v6.int8.onnx",  "layout_model": "dec-B-v2h.onnx"},
  "available":   {"ocr_models": ["..."], "layout_models": ["..."]},
  "selectable_via_domain": ["default", "handwritten", "kramarky", "kurrent"]
}
```

`available` lists every `.onnx` bundled in the package, including superseded files. Only
`selectable_via_domain` values are accepted as a `domain`; pinning a different bundled file
is a server-side setting, described in [Models and domains](models.md#pinning-a-model).

## A complete client

```python
import time
import requests

BASE = "http://localhost:8000"
HEADERS = {}  # {"X-API-Key": "your-secret-key"} when auth is enabled


def ocr_page(path, domain=None, fmt="alto", timeout=300):
    with open(path, "rb") as fh:
        data = {"fmt": fmt}
        if domain:
            data["domain"] = domain
        r = requests.post(f"{BASE}/api/v1/process", files={"image": fh},
                          data=data, headers=HEADERS)
    if r.status_code == 503:
        raise RuntimeError(f"queue full, retry after {r.headers.get('Retry-After', '5')}s")
    r.raise_for_status()
    job_id = r.json()["job_id"]

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        s = requests.get(f"{BASE}/api/v1/status/{job_id}", headers=HEADERS)
        s.raise_for_status()
        job = s.json()
        if job["status"] == "done":
            out = requests.get(f"{BASE}/api/v1/result/{job_id}", headers=HEADERS)
            out.raise_for_status()
            return out.text, job["mean_conf"]
        if job["status"] == "failed":
            raise RuntimeError(job["error"])
        time.sleep(1)
    raise TimeoutError(job_id)


alto, conf = ocr_page("page.jpg", domain="handwritten")
print(f"mean confidence {conf:.3f}")
```

## Legacy endpoints

Kept for older clients. Note that the upload field is named `file`, not `image`, and the
response shapes differ.

| Legacy | Current equivalent |
|---|---|
| `POST /upload` — field `file`, returns `{"id": …}` | `POST /api/v1/process` |
| `GET /status/{job_id}` — `state` is `success` when done | `GET /api/v1/status/{job_id}` |
| `GET /download/{job_id}` — accepts `?which=` | `GET /api/v1/result/{job_id}` |

New integrations should use the `/api/v1/` paths.
