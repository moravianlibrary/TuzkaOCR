# TuzkaOCR

Lightweight OCR pipeline for scanned page and document images, optimized for CPU inference. The system detects page layout and text lines, runs line-level OCR, maps recognized words back to source-image coordinates, and returns either ALTO XML with word bounding boxes or plain text.

## Documentation

Full documentation is in [`docs/`](docs/), published at
**https://moravianlibrary.github.io/TuzkaOCR/**:

| Page | Contents |
|------|----------|
| [Step by step (beginners)](docs/beginners.md) | Guided setup for readers new to the command line |
| [Installation](docs/install.md) | Requirements, install from a checkout, upgrading |
| [CLI](docs/cli.md) | Every flag, domains, batch processing |
| [HTTP API](docs/api.md) | Endpoints, status codes, backpressure, auth, a client |
| [Docker](docs/docker.md) | Compose services, storage, ownership, operations |
| [Configuration](docs/configuration.md) | Every `TUZKAOCR_*` variable, memory sizing |
| [Models and domains](docs/models.md) | What ships, how names resolve, pinning |
| [Output formats](docs/output-formats.md) | ALTO structure, provenance, line roles |
| [Troubleshooting](docs/troubleshooting.md) | Install, quality, memory, service errors |

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
spool/               Optional host scratch for non-Compose deployments
cli.py               Command-line entry point
docs/                Documentation sources (MkDocs)
mkdocs.yml           Documentation site configuration
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
dec-B-v2.onnx
rec-E-v5.int8.onnx
vocab.json
```

Kramarky models:

```text
dec-B-v1k.onnx
rec-E-v4k7.int8.onnx
```

Handwritten models (`domain=handwritten`, Czech handwriting):

```text
dec-B-v2h.onnx
rec-H-v6.int8.onnx
```

Kurrent models (`domain=kurrent`, German Kurrent/Sütterlin script):

```text
dec-B-v2h.onnx
rec-H-v6.int8.onnx
```

`rec-H-v6` is a single general handwritten recognizer serving both
`handwritten` and `kurrent`; it supersedes the earlier Kurrent-only specialist.

The resulting ALTO XML records the layout and recognition models as two `<OCRProcessing>` elements (`IdLayout` / `IdRecognition`, each with an `<ocrProcessingStep>` whose `<processingStepDescription>` is `layout` / `recognition`), so downstream consumers see the explicit provenance pair, e.g. `dec-B-v2` + `rec-E-v5.int8` for default, `dec-B-v1k` + `rec-E-v4k7.int8` for Kramarky, or `dec-B-v2h` + `rec-H-v6.int8` for handwritten and Kurrent.

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

Per-request form fields: `image` (file), `domain` (`kramarky`, `handwritten`, `kurrent`, or omitted for printed), `fmt` (`alto`, `txt`, or `multi`), `role_classifier` (bool, optional). With `fmt=multi` the server produces both ALTO XML and plain text from a single OCR pass; choose which to download with the `?which=alto|txt` query parameter on the result endpoint (defaults to `alto`). The server picks model files from its own configuration — clients cannot supply model paths. Submitting more than `TUZKAOCR_MAX_QUEUE` simultaneous jobs returns **503** with a `Retry-After` header.

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

Submit one image and grab both ALTO and TXT in a single OCR pass:

```bash
JOB=$(curl -s -F "image=@page.jpg" -F "fmt=multi" \
        http://localhost:8000/api/v1/process | jq -r .job_id)
curl -o result.alto.xml "http://localhost:8000/api/v1/result/$JOB"            # default: alto
curl -o result.txt      "http://localhost:8000/api/v1/result/$JOB?which=txt"  # plain text
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

Single image to both ALTO XML and plain text in one pass (`--out` is a stem; suffixes are appended):

```bash
python cli.py page.jpg --format multi --out page
# writes page.alto.xml and page.txt
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
TUZKAOCR_MAX_WIDTH=3400             # max line-crop width fed to the recognizer, in px
TUZKAOCR_CROP_ENDPOINT_EXT=0.0      # extend line crops at both ends, as a fraction of line height
TUZKAOCR_COLUMN_SPLIT=false         # true = order lines column-by-column within a region
TUZKAOCR_ADAPTIVE_DOWNSAMPLE=true   # true = recover dense pages via adaptive downsampling
TUZKAOCR_CPU_MEM_ARENA=true         # false = release RAM to OS between pages (see Memory below)
TUZKAOCR_ROLE_CLASSIFIER=false      # true = tag each ALTO TextLine with role (body/heading/...)
TUZKAOCR_ROLE_MODEL=role-H5.onnx    # bundled role classifier model
TUZKAOCR_RESULTS_DIR=results        # stored API results
TUZKAOCR_MAX_JOB_AGE_HOURS=24       # result cleanup age (in-memory jobs + disk files)
TUZKAOCR_MAX_QUEUE=16               # max simultaneous queued+running jobs (503 above this)
TUZKAOCR_SPOOL_DIR=                 # upload spool directory; empty = system temp directory
```

Result files older than `TUZKAOCR_MAX_JOB_AGE_HOURS` are removed on startup and once per hour. The sweep also covers orphaned files left over from previous server lifetimes, not just jobs currently tracked in memory.

Bad values (e.g. `TUZKAOCR_PAGE_WORKERS=0`, an unknown device, a missing `SPOOL_DIR` path) are rejected at startup with a clear error before models load.

### Model overrides

Each domain resolves a layout model and a recognition model from configuration; clients
cannot supply model paths. The defaults are the bundled files and normally need no
changes:

```text
TUZKAOCR_LAYOUT_MODEL=dec-B-v2.onnx                 # printed (default domain)
TUZKAOCR_OCR_MODEL=rec-E-v5.int8.onnx
TUZKAOCR_KRAMARKY_LAYOUT_MODEL=dec-B-v1k.onnx       # domain=kramarky
TUZKAOCR_KRAMARKY_OCR_MODEL=rec-E-v4k7.int8.onnx
TUZKAOCR_HANDWRITTEN_LAYOUT_MODEL=dec-B-v2h.onnx    # domain=handwritten
TUZKAOCR_HANDWRITTEN_OCR_MODEL=rec-H-v6.int8.onnx
TUZKAOCR_KURRENT_LAYOUT_MODEL=dec-B-v2h.onnx        # domain=kurrent
TUZKAOCR_KURRENT_OCR_MODEL=rec-H-v6.int8.onnx
TUZKAOCR_VOCAB=vocab.json                           # shared recognizer character set
```

A value that names an existing file is used as given (`~` is expanded); otherwise its
filename is looked up in the bundled `tuzkaocr/models/` directory. An unresolvable name
fails at startup with a message listing what is bundled. Superseded model files stay
bundled, so a pin to an older model keeps working after an upgrade — for example
`TUZKAOCR_KURRENT_OCR_MODEL=rec-H-v3h-kurrent.int8.onnx` restores the pre-`rec-H-v6`
Kurrent specialist. `TUZKAOCR_VOCAB` is shared by every recognizer and must match the
models in use; override it only alongside a custom recognizer.

## Adaptive downsampling

The layout model runs at a fixed downsample by default. On dense, multi-column pages (periodicals, classifieds) that resolution is too coarse: lines are missed or their geometry is imprecise and the recognized text degrades. With adaptive downsampling enabled (the default), each page is first processed at the standard downsample; if it looks resolution-starved (overlapping baselines or low recognition confidence) the page is re-processed at a finer downsample, and the result with the highest recognition confidence is kept.

Dense pages that escalate cost roughly 2–3x the per-page time for a large quality gain. Disable per request is not supported; control it server-side:

```text
TUZKAOCR_ADAPTIVE_DOWNSAMPLE=true   # default; set false for fixed single-pass layout
```

The CLI exposes `--no-adaptive` to force the fixed single-pass path.

## Line role classification (experimental)

Off by default. When enabled, every recognized line is tagged with one of `body`, `heading` (title / section heading), `header` (running page header), `footer` (running page footer), or `page_number`. Each role surfaces as an ALTO `<StructureTag>` (in `<Tags>`) referenced from the relevant `<TextLine>` via `TAGREFS`.

It runs once per page after OCR completes; cost is a few ms per typical page.

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
TUZKAOCR_MAX_IMAGE_PIXELS=300000000 # fail accepted API jobs over this decoded pixel count
```

Defaults are generous to support large archival scans. Tune down for stricter deployments. Oversize uploads return a clean **413** for both `Content-Length`-known and chunked/streaming requests. Corrupt or over-pixel-limit images are accepted asynchronously and become failed jobs; command-line processing has no API pixel limit.

Every accepted upload is streamed to a uniquely named service-owned file under
`TUZKAOCR_SPOOL_DIR` (or the system temp directory if unset). Its worker decodes it once;
queued jobs never retain decoded page arrays. The file is removed after processing or a
rejected submission. An explicitly configured spool directory is treated as private to
one service instance and crash leftovers are cleared at startup; do not share it between
bare-metal instances. The shared system temp directory is never swept.
Docker Compose gives the CPU and GPU services separate disk-backed spool volumes so one
service cannot interfere with the other's uploads.

### Memory

Peak memory is driven by the layout detector, a fully-convolutional segmentation net run
at up to ~1536 px. Its fp32 activations are a **~1.3 GiB transient per page in flight** —
the model files themselves (3 MB) and decoded pages (~10 MB) are negligible by comparison.
A rough sizing guide:

```text
peak ≈ 0.1 GiB  +  PAGE_WORKERS × ~1.3 GiB  +  scratch
```

`TUZKAOCR_MAX_QUEUE` limits queued plus running jobs. Queued uploads remain encoded on
disk, so `TUZKAOCR_PAGE_WORKERS` is the main memory-control lever. For tight memory
limits, prefer **one page worker per engine and scale out by engine count** rather than
packing more workers into one engine.

`TUZKAOCR_CPU_MEM_ARENA` (default `true`) controls ONNX Runtime's CPU memory arena:

- **`true`** (default): ORT keeps a reusable allocation pool. Lowest per-page latency, but
  the pool grows to the peak working set and is **not returned to the OS** — idle RSS stays
  high (~2.4 GiB with two workers), so a tight container limit can OOM on the next page.
- **`false`**: memory is released back to the OS between pages. Peak RSS drops ~45% and idle
  RSS falls to ~0.26 GiB, at roughly **+35% single-page latency but only ~−6% batch
  throughput** (the work is compute-bound). **Recommended for memory-constrained bulk
  workloads** where avoiding OOM matters more than single-page
  latency.

With `TUZKAOCR_CPU_MEM_ARENA=false`, `PAGE_WORKERS=2` fits a ~2 GiB limit and `PAGE_WORKERS=1`
fits ~1.2 GiB. Also ensure scratch (`SPOOL_DIR`, results) is on real disk, not RAM-backed
tmpfs — tmpfs counts against the container memory limit.

## Production Notes

- Keep `results/` on persistent storage.
- Point `TUZKAOCR_SPOOL_DIR` at real disk storage. The bundled Compose setup uses separate named volumes for CPU and GPU. If the spool ends up on a tmpfs / RAM-backed filesystem, large uploads consume memory instead of disk.
- Run behind a reverse proxy or ingress that provides TLS.
- Enable API-key authentication for any non-local deployment.
- Tune `TUZKAOCR_PAGE_WORKERS`, `TUZKAOCR_LINE_WORKERS`, and `TUZKAOCR_OCR_THREADS` for the target CPU/GPU capacity.
- `/healthz` is intentionally unauthenticated for container health checks.

## License

The source code is licensed under the Apache License, Version 2.0. See `LICENSE`
and `NOTICE`.

The model artifacts in `tuzkaocr/models/` are licensed separately under CC BY-NC-SA 4.0.
See `tuzkaocr/models/LICENSE`.
