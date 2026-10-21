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

    Interactive OpenAPI documentation is served at `/docs`, and the schema at
`/openapi.json`.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/healthz` | Liveness, core version, and whether valid custom packs are loaded; never authenticated |
| `GET` | `/api/v1/version` | Core version and custom domain pack status |
| `POST` | `/api/v1/process` | Submit an image, receive a job ID |
| `GET` | `/api/v1/status/{job_id}` | Job state, line count, mean confidence |
| `GET` | `/api/v1/result/{job_id}` | Download the finished output |
| `GET` | `/api/v1/models` | Configured and bundled models, including loaded custom domains |

Legacy-compatible aliases exist for older clients — see [below](#legacy-endpoints).

## Submitting a page

`POST /api/v1/process`, as `multipart/form-data`:

| Field | Type | Default | Values |
|---|---|---|---|
| `image` | file | *required* | JPEG, PNG, or TIFF |
| `domain` | string | printed | `default`, `print`, a built-in domain, or a loaded pack name |
| `fmt` | string | `alto` | `alto`, `page`, `txt`, `multi` |
| `role_classifier` | bool | server default | `true` / `false` |
| `alto_profile` | string | server default (`ndk`) | `ndk`, `basic` |
| `orientation` | string | server default (`off`) | `off`, `auto` |
| `orientation_threshold` | float | server default (`0.9`) | 0–1 |
| `contrast` | string | server default (`off`) | `off`, `on`, `auto`, `line` |
| `source_identifier` | string | *none* | Written into the ALTO as `fileIdentifier` |
| `physical_img_nr` | int | *from the filename* | Sequential page number within the volume; must be >=1 |

```bash
curl -F "image=@page.jpg" http://localhost:8000/api/v1/process
```

```json
{"job_id": "3f2b1c8e-5d47-4a19-9c33-8e1f0a7b6d24", "status": "queued"}
```

Invalid format and setting values are rejected with **400** before the job is created. An
unknown domain returns **422** and lists the built-in domains and loaded pack names. `default`
uses a pack marked as default, when present; `print` always selects the built-in print domain.

`orientation` and `contrast` are explained in [Configuration](configuration.md#page-orientation).

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
  "orientation_angle": 0,
  "orientation_confidence": null,
  "orientation_classifier_confidence": null,
  "orientation_method": "off",
  "error": null
}
```

`status` is `queued`, `running`, `done`, or `failed`. A low `mean_conf` flags pages worth
checking. The `orientation_*` fields report the rotation applied to make the page upright
and how it was chosen (`off`, `classifier`, `probe` or `recheck`).

```bash
curl -o result.txt "http://localhost:8000/api/v1/result/$JOB"
```

The result endpoint returns **202** while the job is still running, so you can poll it
directly.

### Getting both formats

With `fmt=multi` the server produces ALTO and text from one OCR pass, and `?which=`
chooses which to download. It defaults to `alto`.

```bash
JOB=$(curl -s -F "image=@page.jpg" -F "fmt=multi" \
        http://localhost:8000/api/v1/process | jq -r .job_id)

curl -o result.alto.xml "http://localhost:8000/api/v1/result/$JOB"
curl -o result.txt      "http://localhost:8000/api/v1/result/$JOB?which=txt"
```

## Status codes

| Code | When |
|---|---|
| `200` | Result returned |
| `202` | Job accepted but still `queued` or `running` |
| `400` | Unknown `fmt`, `alto_profile`, `which`, or an invalid `physical_img_nr` |
| `401` | Missing or invalid API key, when authentication is enabled |
| `404` | Unknown job ID, or no result file for it |
| `413` | Request body exceeds `TUZKAOCR_MAX_UPLOAD_MB` |
| `422` | Unknown `domain`, the image could not be decoded, or it exceeds `TUZKAOCR_MAX_IMAGE_PIXELS` |
| `500` | Processing failed for another reason; `error` carries the message |
| `503` | Queue is full; a `Retry-After: 5` header is included |

Images are decoded after upload, so a corrupt or oversized image becomes a **failed job**
and the result endpoint answers **422**.

## Backpressure

`TUZKAOCR_MAX_QUEUE` (default 16) caps queued plus running jobs; above it the server returns
**503** with `Retry-After: 5`. Concurrency is set by `TUZKAOCR_PAGE_WORKERS`.

## Job lifetime and retention

Jobs and their result files are deleted after `TUZKAOCR_MAX_JOB_AGE_HOURS` (default 24).
Job status is kept in memory, so after a restart `status` answers **404**, but `result` still
serves files that remain on disk.

## Authentication

Off by default, which is only safe on a trusted network. Two modes, both using the
`X-API-Key` header. For Docker, see [Setting an API key](docker.md#setting-an-api-key).

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

`/healthz` is never authenticated, so health checks keep working. It returns only the core
version and a `custom` boolean; pack names are not exposed on this public endpoint:

```json
{"status": "ok", "version": "1.10.0", "custom": false}
```

`GET /api/v1/version` uses the API key when authentication is enabled and lists pack names,
versions, bases, and any skipped-pack reason:

```json
{
  "version": "1.10.0",
  "custom": true,
  "default_domain": "slovak",
  "domains": [
    {"name": "slovak", "version": "1.0.0", "title": "Slovak print", "base": "print",
     "ocr_model": "rec-sk.onnx", "default": true, "status": "ok", "reason": null}
  ]
}
```

## Listing models

```bash
curl -s http://localhost:8000/api/v1/models
```

```json
{
  "version": "1.10.0",
  "defaults":    {"ocr_model": "rec-E-v7.onnx",  "layout_model": "dec-B-v2.onnx", "height_scale": 1.0},
  "kramarky":    {"ocr_model": "rec-E-v4k7.onnx", "layout_model": "dec-B-v1k.onnx"},
  "handwritten": {"ocr_model": "rec-I-v2.onnx",  "layout_model": "dec-B-v2h.onnx"},
  "kurrent":     {"ocr_model": "rec-I-v2.onnx",  "layout_model": "dec-B-v2h.onnx"},
  "domains":     [{"name": "slovak", "version": "1.0.0", "base": "print", "status": "ok"}],
  "slovak":      {"ocr_model": "rec-sk.onnx", "layout_model": "dec-B-v2.onnx"},
  "available":   {"ocr_models": ["..."], "layout_models": ["..."]},
  "selectable_via_domain": ["default", "handwritten", "kramarky", "kurrent", "slovak"]
}
```

Loaded packs appear under their own key and in `selectable_via_domain`. Only the public
`/healthz` endpoint omits pack names; the API-key-protected version and models endpoints list
them. Pinning another model is a [server-side setting](models.md#pinning-a-model).

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

Kept for older clients; the upload field is `file`, not `image`.

| Legacy | Current equivalent |
|---|---|
| `POST /upload` — field `file`, returns `{"id": …}` | `POST /api/v1/process` |
| `GET /status/{job_id}` — `state` is `success` when done | `GET /api/v1/status/{job_id}` |
| `GET /download/{job_id}` — accepts `?which=` | `GET /api/v1/result/{job_id}` |

New integrations should use the `/api/v1/` paths.
