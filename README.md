# TuzkaOCR

Lightweight OCR pipeline for scanned page and document images, optimized for CPU inference. The system detects page layout and text lines, runs line-level OCR, maps recognized words back to source-image coordinates, and returns either ALTO XML with word bounding boxes or plain text.

## Features

- Lightweight: ~12 MB of model artifacts, no GPU required, runs anywhere ONNX Runtime runs.
- Page OCR for scanned documents, archival material, and newspapers.
- ALTO XML output with page, block, line, and word coordinates.
- CPU and GPU Docker images.
- FastAPI service with asynchronous job processing.
- CLI for single-image and batch processing.
- Optional API-key authentication.
- Per-request domain selection.

## Pipeline

1. Load the input image with OpenCV.
2. Detect regions, baselines, and line heights using the layout model.
3. Extract perspective-corrected line crops.
4. Run OCR recognition with ONNX Runtime.
5. Build structured output as ALTO XML or plain text.
6. Store API job results under `results/`.

## Repository Layout

```text
api/                 FastAPI application and routes
tuzkaocr/            OCR pipeline package
tuzkaocr/layout/     Layout detection and post-processing
tuzkaocr/ocr/        ONNX OCR recognizer and vocabulary handling
tuzkaocr/models/     Bundled layout and OCR model files (shipped in the wheel)
results/             Runtime OCR outputs, mounted as persistent storage
spool/               Disk-backed scratch for large uploads (Compose-mounted)
cli.py               Command-line entry point
Dockerfile           CPU container image
Dockerfile.gpu       GPU container image
docker-compose.yml   Production-oriented Compose setup
tuzkaocr.env         Runtime configuration
api_keys.example.yaml  Optional multi-user API-key file (template; real file is gitignored)
```

## Models

Both layout and OCR models are ONNX, served via ONNX Runtime.

Default models:

```text
dec-A-v4.onnx
rec-E-v5.int8.onnx
vocab.json
```

Kramarky models:

```text
dec-A-v3k5.onnx
rec-E-v4k7.int8.onnx
```

The resulting ALTO XML records both the layout and recognition models under `<OCRProcessing>/<ocrProcessingStep>` entries (`<processingStepDescription>` = `layout` / `recognition`), so downstream consumers see the explicit provenance pair, e.g. `dec-A-v4` + `rec-E-v5.int8` for default, or `dec-A-v3k5` + `rec-E-v4k7.int8` for Kramarky.

## Platform support

Linux, Windows, and Apple Silicon macOS are supported. **Intel Macs are not** — upstream `onnxruntime` no longer ships x86_64 macOS wheels (1.18+ are arm64-only), so `pip install` will fail. Use the Docker CPU image instead.

## Docker Deployment

Build and run the CPU API service:

```bash
docker compose up --build -d cpu
```

The API listens on `8000` by default. Override the host port if needed:

```bash
TUZKAOCR_CPU_PORT=18080 docker compose up --build -d cpu
```

Run the GPU service:

```bash
docker compose --profile gpu up --build -d gpu
```

The GPU service uses port `8001` by default and requires NVIDIA Container Toolkit. The GPU image is provided for completeness but is not yet performance-tuned (pre/post-processing layout differs from CPU); CPU deployment is the recommended path for now.

Health check:

```bash
curl http://localhost:8000/healthz
```

## API Usage

Per-request form fields: `image` (file), `domain` (`kramarky` or omitted), `height_scale` (float), `fmt` (`alto` or `txt`). The server picks model files from its own configuration — clients cannot supply model paths. Submitting more than `TUZKAOCR_MAX_QUEUE` simultaneous jobs returns **503** with a `Retry-After` header.

Submit an image for ALTO XML output:

```bash
curl -F "image=@page.jpg" \
  http://localhost:8000/api/v1/process
```

Submit an image for plain text with Kramarky models:

```bash
curl -F "image=@page.jpg" \
  -F "domain=kramarky" \
  -F "fmt=txt" \
  http://localhost:8000/api/v1/process
```

Check status:

```bash
curl http://localhost:8000/api/v1/status/JOB_ID
```

Download result:

```bash
curl -o result.txt http://localhost:8000/api/v1/result/JOB_ID
```

List available models:

```bash
curl http://localhost:8000/api/v1/models
```

Legacy-compatible endpoints are also available:

```text
POST /upload
GET  /status/{job_id}
GET  /download/{job_id}
```

## CLI Usage

After `pip install .` the `tuzkaocr` entry-point is on `PATH` and can be used in place of `python cli.py` in any of the examples below.

Single image to ALTO XML:

```bash
python cli.py page.jpg --out result.alto.xml
# or, after install:
tuzkaocr page.jpg --out result.alto.xml
```

Single image to plain text:

```bash
python cli.py page.jpg --format txt --out result.txt
```

Batch directory to plain text with Kramarky models:

```bash
python cli.py input_pages/ \
  --batch \
  --format txt \
  --domain kramarky \
  --out-dir results/ \
  --workers 2
```

Run the same batch through Docker CPU with a local input directory mounted for this command:

```bash
docker compose run --rm --no-deps \
  -v "$PWD/input_pages:/app/input:ro" \
  cpu python cli.py /app/input \
  --batch \
  --format txt \
  --domain kramarky \
  --out-dir /app/results \
  --workers 2
```

## Configuration

Runtime settings are loaded from environment variables with the `TUZKAOCR_` prefix. The Docker Compose setup uses `tuzkaocr.env`.

Important settings:

```text
TUZKAOCR_DEVICE=cpu                 # cpu | cuda | auto
TUZKAOCR_OCR_THREADS=4              # ONNX intra-op threads
TUZKAOCR_LINE_WORKERS=4             # OCR threads per page
TUZKAOCR_PAGE_WORKERS=2             # API/background or batch workers
TUZKAOCR_HEIGHT_SCALE=1.0           # line-height multiplier
TUZKAOCR_ADAPTIVE_DOWNSAMPLE=true   # true = recover dense pages via adaptive downsampling
TUZKAOCR_ROLE_CLASSIFIER=false      # true = tag each ALTO TextLine with role (body/heading/...)
TUZKAOCR_ROLE_MODEL=role-G-v1.npz   # bundled role classifier model
TUZKAOCR_RESULTS_DIR=results        # stored API results
TUZKAOCR_MAX_JOB_AGE_HOURS=24       # result cleanup age (in-memory jobs + disk files)
TUZKAOCR_MAX_QUEUE=16               # max simultaneous queued+running jobs (503 above this)
TUZKAOCR_SPOOL_DIR=                 # optional disk dir for large upload spill; empty = system /tmp
```

Result files older than `TUZKAOCR_MAX_JOB_AGE_HOURS` are removed on startup and once per hour. The sweep also covers orphaned files left over from previous server lifetimes, not just jobs currently tracked in memory.

Bad values (e.g. `TUZKAOCR_PAGE_WORKERS=0`, an unknown device, a missing `SPOOL_DIR` path) are rejected at startup with a clear error before models load.

## Adaptive downsampling

The layout model runs at a fixed downsample by default. On dense, multi-column pages (periodicals, classifieds) that resolution is too coarse: lines are missed or their geometry is imprecise and the recognized text degrades. With adaptive downsampling enabled (the default), each page is first processed at the standard downsample; if it looks resolution-starved (overlapping baselines or low recognition confidence) the page is re-processed at a finer downsample, and the result with the highest recognition confidence is kept.

Dense pages that escalate cost roughly 2–3x the per-page time for a large quality gain. Disable per request is not supported; control it server-side:

```text
TUZKAOCR_ADAPTIVE_DOWNSAMPLE=true   # default; set false for fixed single-pass layout
```

The CLI exposes `--no-adaptive` to force the fixed single-pass path.

## Line role classification (experimental)

Off by default. When enabled, every recognized line is tagged with one of `body`, `prominent` (title / heading), `pagenum`, or `header` (running page header), and the role surfaces as a `TYPE` attribute on each `<TextLine>` in the ALTO output.

It runs once per page after OCR completes; cost is well under 5 ms per typical page.

Three ways to enable, identical effect:

```text
TUZKAOCR_ROLE_CLASSIFIER=true       # server-wide default (env)
```

```bash
python cli.py page.jpg --role-classifier --format alto   # per-invocation (CLI)
```

```bash
curl -F image=@page.jpg -F role_classifier=true http://localhost:8000/api/v1/process   # per-request (API)
```

The classifier prefers silence over wrong markup: when it isn't confident, the line stays `body`. Mistakes show up as a missing role tag, never an incorrect one.

## Authentication

Recommended (simple): set a single shared secret.

```text
TUZKAOCR_API_KEY=your-secret-key
```

Send requests with:

```bash
curl -H "X-API-Key: your-secret-key" http://localhost:8000/api/v1/models
```

Disabled (default, only safe on a trusted network): leave both `TUZKAOCR_API_KEY` and `TUZKAOCR_API_KEYS_FILE` blank.

Multi-user (when you need per-caller identity in logs): copy the example file, fill in keys, mount it, and point the env var at it.

```bash
cp api_keys.example.yaml api_keys.yaml
$EDITOR api_keys.yaml
```

`api_keys.yaml` format:

```yaml
user-name: generated-secret-key
integration-name: another-generated-secret-key
```

Then in `docker-compose.yml` add a volume entry under the service:

```yaml
    volumes:
      - ./api_keys.yaml:/app/api_keys.yaml:ro
```

and set `TUZKAOCR_API_KEYS_FILE=/app/api_keys.yaml`. When set, it takes precedence over `TUZKAOCR_API_KEY`. The key file is reloaded every 10 s, so keys can be rotated without restarting. Generate keys with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

Startup fails fast with a clear message if `TUZKAOCR_API_KEYS_FILE` points at a missing, empty, or unparseable file.

## Request limits

```text
TUZKAOCR_MAX_UPLOAD_MB=256          # reject HTTP body over this size (413)
TUZKAOCR_MAX_IMAGE_PIXELS=300000000 # reject decoded images over this pixel count (422)
```

Defaults are generous to support large archival scans. Tune down for stricter deployments. Oversize uploads return a clean **413** for both `Content-Length`-known and chunked/streaming requests.

Uploads up to 8 MiB are held in memory; anything larger spills to disk under `TUZKAOCR_SPOOL_DIR` (or the system temp directory if unset). Under Docker Compose the bundled `./spool` bind-mount is used so the spool is real disk, not RAM-backed tmpfs.

## Production Notes

- Keep `results/` on persistent storage.
- Point `TUZKAOCR_SPOOL_DIR` at a real disk volume (the bundled Compose setup uses `./spool`). If the spool ends up on a tmpfs / RAM-backed filesystem, large uploads consume memory instead of disk.
- Run behind a reverse proxy or ingress that provides TLS.
- Enable API-key authentication for any non-local deployment.
- Tune `TUZKAOCR_PAGE_WORKERS`, `TUZKAOCR_LINE_WORKERS`, and `TUZKAOCR_OCR_THREADS` for the target CPU/GPU capacity.
- `/healthz` is intentionally unauthenticated for container health checks.

## License

The source code is licensed under the Apache License, Version 2.0. See `LICENSE`
and `NOTICE`.

The model artifacts in `tuzkaocr/models/` are licensed separately under CC BY-NC-SA 4.0.
See `tuzkaocr/models/LICENSE`.
