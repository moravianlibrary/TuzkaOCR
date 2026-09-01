# Configuration

Every runtime setting is an environment variable prefixed `TUZKAOCR_`. The same values back
the CLI, so a variable sets the default and a command-line flag overrides it for that
invocation.

## Where settings come from

Precedence, highest first:

1. Command-line flags (CLI only).
2. Real environment variables.
3. `.env` in the current working directory.
4. `tuzkaocr.env` next to the package directory.

Both files are loaded without overriding what is already set, so an exported variable always
beats a file.

!!! warning "`tuzkaocr.env` only applies to a checkout"
    It is looked up one level above the `tuzkaocr/` package directory. In a clone that is
    the repository root, so the file works. After `pip install .` the package lives in
    `site-packages/`, where no such file exists — an installed `tuzkaocr` command reads
    only real environment variables and `.env` in the working directory. The Docker images
    copy `tuzkaocr.env` into `/app`, so it applies there.

## Validation

Configuration is validated before models load, and a bad value aborts startup with a message
naming every problem at once:

```
Invalid configuration:
  - TUZKAOCR_PAGE_WORKERS must be >0, got 0
  - TUZKAOCR_DEVICE must be one of ('cpu', 'cuda', 'auto'), got 'gpu'
```

Rules: the thread, worker, size, and age counters must be greater than zero;
`TUZKAOCR_DEVICE` must be `cpu`, `cuda`, or `auto`; `TUZKAOCR_HEIGHT_SCALE` must be between
0.1 and 10.0; and `TUZKAOCR_SPOOL_DIR`, when set, must already exist and be writable.

Booleans accept `1`, `true`, or `yes`, case-insensitively — anything else is false, so
`on`, `y`, and `enabled` all read as false. A non-numeric value for a numeric setting raises
a `ValueError` naming the variable.

## Compute and concurrency

| Variable | Default | Effect |
|---|---|---|
| `TUZKAOCR_DEVICE` | `cpu` | `cpu`, `cuda`, or `auto` |
| `TUZKAOCR_OCR_THREADS` | `4` | ONNX Runtime intra-op threads |
| `TUZKAOCR_LINE_WORKERS` | `4` | Parallel line-recognition threads per page |
| `TUZKAOCR_PAGE_WORKERS` | `2` | Concurrent pages — API worker threads, or CLI batch processes |
| `TUZKAOCR_CPU_MEM_ARENA` | `true` | ONNX Runtime CPU memory arena; see [memory](#memory) |

`auto` resolves to `cuda` only when `onnxruntime` reports a CUDA execution provider, and to
`cpu` otherwise. The plain `onnxruntime` wheel is CPU-only.

`TUZKAOCR_PAGE_WORKERS` is the main lever for both throughput and memory. The three
concurrency settings multiply: total threads land near
`PAGE_WORKERS × LINE_WORKERS × OCR_THREADS`, so oversubscribing a small machine slows it
down.

## Recognition quality

| Variable | Default | Effect |
|---|---|---|
| `TUZKAOCR_HEIGHT_SCALE` | `1.0` | Multiplies predicted line heights (valid range 0.1–10.0) |
| `TUZKAOCR_MAX_WIDTH` | `3400` | Maximum line-crop width fed to the recognizer, in pixels |
| `TUZKAOCR_ADAPTIVE_DOWNSAMPLE` | `true` | Re-run resolution-starved pages at a finer downsample |
| `TUZKAOCR_CROP_ENDPOINT_EXT` | `0.0` | Extend line crops at both ends, as a fraction of line height |
| `TUZKAOCR_COLUMN_SPLIT` | `false` | Order lines column-by-column within a region |

!!! note "Two of these are set per domain"
    `CROP_ENDPOINT_EXT` and `COLUMN_SPLIT` are chosen by the selected domain — `0.3` and
    `true` for `handwritten` and `kurrent`, `0.0` and `false` otherwise — which overrides
    the environment value. Your setting survives only for the printed domain on the API
    path. Treat them as tuning knobs for the printed models, not as global switches.

### Adaptive downsampling

The layout model runs at a fixed downsample by default. On dense, multi-column pages that
resolution is too coarse: lines get missed, geometry becomes imprecise, and recognition
degrades. With adaptive downsampling on, each page is processed at the standard downsample
first; if it looks resolution-starved — overlapping baselines or low confidence — it is
reprocessed finer and the highest-confidence result wins.

Pages that escalate cost roughly 2–3× the per-page time. It cannot be switched off per
request; set `TUZKAOCR_ADAPTIVE_DOWNSAMPLE=false` server-side, or pass `--no-adaptive` on
the CLI.

## Line roles

| Variable | Default | Effect |
|---|---|---|
| `TUZKAOCR_ROLE_CLASSIFIER` | `false` | Tag each ALTO line with a structural role |
| `TUZKAOCR_ROLE_MODEL` | `role-H5.onnx` | Bundled role classifier |

This is the server-wide default; the API's `role_classifier` form field and the CLI's
`--role-classifier` flag override it per request. See
[Output formats](output-formats.md#line-roles).

## Service limits and storage

| Variable | Default | Effect |
|---|---|---|
| `TUZKAOCR_RESULTS_DIR` | `results` | Where finished output is written |
| `TUZKAOCR_SPOOL_DIR` | *system temp* | Where uploads are streamed |
| `TUZKAOCR_MAX_JOB_AGE_HOURS` | `24` | Retention for jobs and result files |
| `TUZKAOCR_MAX_QUEUE` | `16` | Maximum queued + running jobs before 503 |
| `TUZKAOCR_MAX_UPLOAD_MB` | `256` | Request body limit; over this returns 413 |
| `TUZKAOCR_MAX_IMAGE_PIXELS` | `300000000` | Decoded pixel limit; over this fails the job with 422 |

The defaults are generous to accommodate large archival scans; tune down for stricter
deployments. The pixel limit applies to API jobs only — command-line processing has no
pixel cap.

Every accepted upload is streamed to a uniquely named file under the spool directory, decoded
once by its worker, and deleted after processing or rejection. Queued jobs hold the encoded
file on disk, never a decoded page in memory.

An explicitly configured spool directory is treated as private to one service instance and is
cleared of leftovers at startup — do not share one between instances. The shared system temp
directory is never swept. Keep the spool on real disk: on a RAM-backed `tmpfs`, large uploads
consume memory instead.

## Authentication

| Variable | Default | Effect |
|---|---|---|
| `TUZKAOCR_API_KEY` | *empty* | Single shared secret, sent as `X-API-Key` |
| `TUZKAOCR_API_KEYS_FILE` | *empty* | YAML file of `name: key` pairs; takes precedence |

Both empty means authentication is disabled, which is only safe on a trusted network. Details
in [HTTP API](api.md#authentication).

## Models

| Variable | Default |
|---|---|
| `TUZKAOCR_LAYOUT_MODEL` | `dec-B-v2.onnx` |
| `TUZKAOCR_OCR_MODEL` | `rec-E-v5.int8.onnx` |
| `TUZKAOCR_KRAMARKY_LAYOUT_MODEL` | `dec-B-v1k.onnx` |
| `TUZKAOCR_KRAMARKY_OCR_MODEL` | `rec-E-v4k7.int8.onnx` |
| `TUZKAOCR_HANDWRITTEN_LAYOUT_MODEL` | `dec-B-v2h.onnx` |
| `TUZKAOCR_HANDWRITTEN_OCR_MODEL` | `rec-H-v6.int8.onnx` |
| `TUZKAOCR_KURRENT_LAYOUT_MODEL` | `dec-B-v2h.onnx` |
| `TUZKAOCR_KURRENT_OCR_MODEL` | `rec-H-v6.int8.onnx` |
| `TUZKAOCR_VOCAB` | `vocab.json` |

The defaults are the bundled files and normally need no change. See
[Models and domains](models.md) for how a name is resolved and when pinning makes sense.

## Memory

Peak memory is dominated by the layout detector — a fully convolutional segmentation network
run at up to about 1536 px. Its fp32 activations are a **transient of roughly 1.3 GiB per
page in flight**. The model files themselves (3–12 MB) and decoded pages (~10 MB) are
negligible next to that.

```
peak ≈ 0.1 GiB + PAGE_WORKERS × 1.3 GiB + scratch
```

`TUZKAOCR_CPU_MEM_ARENA` controls ONNX Runtime's CPU memory arena:

| Value | Behaviour | Cost |
|---|---|---|
| `true` (default) | A reusable allocation pool is kept. Lowest per-page latency, but the pool grows to the peak working set and is **never returned to the OS** — idle RSS stays high, around 2.4 GiB with two workers. | A tight container limit can OOM on a later page. |
| `false` | Memory is released between pages. Peak RSS drops about 45%, idle RSS falls to roughly 0.26 GiB. | About +35% single-page latency, but only about −6% batch throughput — the work is compute-bound. |

`false` is the recommendation for memory-constrained bulk work, where avoiding an OOM matters
more than single-page latency. With it, two page workers fit in about 2 GiB and one fits in
about 1.2 GiB.

For tight limits, prefer **one page worker per service instance, scaled out by instance
count**, over packing more workers into one process. And keep scratch — the spool and results
directories — on real disk, since `tmpfs` counts against a container's memory limit.
