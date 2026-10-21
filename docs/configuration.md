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
    It is read from the repository root, so it works from a clone and in the Docker images.
    An installed `tuzkaocr` command reads only environment variables and `.env` in the
    working directory.

## Validation

Configuration is validated before models load, and a bad value aborts startup with a message
naming every problem at once:

```
Invalid configuration:
  - TUZKAOCR_PAGE_WORKERS must be >0, got 0
  - TUZKAOCR_DEVICE must be one of ('cpu', 'cuda', 'auto'), got 'gpu'
```

Booleans accept `1`, `true`, or `yes` (case-insensitive); anything else, including `on`, is
false.

## Compute and concurrency

| Variable | Default | Effect |
|---|---|---|
| `TUZKAOCR_DEVICE` | `cpu` | `cpu`, `cuda`, or `auto` |
| `TUZKAOCR_OCR_THREADS` | `4` | ONNX Runtime intra-op threads |
| `TUZKAOCR_LINE_WORKERS` | `4` | Parallel line-recognition threads per page |
| `TUZKAOCR_PAGE_WORKERS` | `2` | Concurrent pages — API worker threads, or CLI batch processes |
| `TUZKAOCR_CPU_MEM_ARENA` | `true` | ONNX Runtime CPU memory arena; see [memory](#memory) |

`TUZKAOCR_PAGE_WORKERS` is the main lever for both throughput and memory. Total threads land
near `PAGE_WORKERS × LINE_WORKERS × OCR_THREADS`, so do not oversubscribe a small machine.

## Recognition quality

| Variable | Default | Effect |
|---|---|---|
| `TUZKAOCR_HEIGHT_SCALE` | `1.0` | Multiplies predicted line heights (valid range 0.1–10.0) |
| `TUZKAOCR_MAX_WIDTH` | `3400` | Maximum line-crop width fed to the recognizer, in pixels |
| `TUZKAOCR_ADAPTIVE_DOWNSAMPLE` | `true` | Size the printed layout pass to each page's text size (never for `handwritten`, `kurrent` or `kramarky`) |
| `TUZKAOCR_LAYOUT_LINE_HEIGHT` | `12` | Target text-line height, in pixels, at the layout model input when adaptive downsampling is on (valid range 4–64); `0` falls back to the fixed downsample |
| `TUZKAOCR_READING_ORDER` | `columns` | Order of text blocks on printed pages: `columns` (column by column, aware of printed rules) or `basic` (horizontal bands, left to right); see [reading order](#reading-order) |
| `TUZKAOCR_LARGE_TEXT` | `true` | Extra layout pass for text far larger than the body text, such as newspaper mastheads; see [large text](#large-text) |
| `TUZKAOCR_CROP_ENDPOINT_EXT` | `0.0` | Extend line crops at both ends, as a fraction of line height |
| `TUZKAOCR_COLUMN_SPLIT` | `false` | Order lines column-by-column within a region |
| `TUZKAOCR_CONTRAST` | `off` | `off`, `on`, `auto` or `line`; see [contrast normalisation](#contrast-normalisation) |
| `TUZKAOCR_CONTRAST_INK` | `120` | `auto` threshold |
| `TUZKAOCR_ORIENTATION` | `off` | `off` or `auto`; see [page orientation](#page-orientation) |
| `TUZKAOCR_ORIENTATION_MODEL` | `orient-A.onnx` | Orientation classifier |
| `TUZKAOCR_ORIENTATION_THRESHOLD` | `0.9` | Below this classifier confidence, all four angles are tried |
| `TUZKAOCR_ORIENTATION_PROBE` | `on` | `off` trusts the classifier alone |
| `TUZKAOCR_ORIENTATION_RECHECK` | `off` | Retry other angles on low-confidence pages |
| `TUZKAOCR_ORIENTATION_RECHECK_CONF` | `0.80` | Recheck below this mean character confidence |
| `TUZKAOCR_ORIENTATION_RECHECK_CHARS` | `200` | Recheck only pages with at least this many characters |

`CROP_ENDPOINT_EXT` and `COLUMN_SPLIT` are set by the domain (`0.3` and `true` for
`handwritten` and `kurrent`), so the environment value only affects printed pages.

### Contrast normalisation

Helps with pale carbon copies and faint typewriting. Normalisation stretches the darkest ink
to black and the paper to white. `on` does this for every page, `auto` only for pages whose
darkest ink is lighter than `TUZKAOCR_CONTRAST_INK`, and `line` for each line crop. Off by
default; coordinates are not affected.

### Page orientation

Off by default. With `TUZKAOCR_ORIENTATION=auto`, a small classifier guesses whether a page
is turned by 90°, 180° or 270°. A page is only rotated if OCR at that angle is clearly more
confident than upright; when the classifier is unsure, all four angles are tried. Upright
pages the classifier is sure about need no extra OCR pass.

`TUZKAOCR_ORIENTATION_RECHECK=on` also retries the other angles on pages that came out with
low confidence. It catches some upside-down pages the classifier missed, at the cost of
extra OCR passes. Output coordinates stay in the original image; see
[output formats](output-formats.md#page-orientation).

### Adaptive downsampling

The layout model works best when text lines reach it about 12 pixels tall. With adaptive
downsampling on (the default), each printed page's typical line height is estimated first
and the page is scaled so its lines land at `TUZKAOCR_LAYOUT_LINE_HEIGHT` pixels. Small
newspaper type gets a finer layout pass, large book type a coarser one. Broadsheets cost
about 2× in layout; ordinary pages cost the same as a fixed pass.

Set `TUZKAOCR_ADAPTIVE_DOWNSAMPLE=false` (CLI `--no-adaptive`) to use the fixed downsample.
The `handwritten`, `kurrent` and `kramarky` domains always use the fixed downsample.

### Reading order

The order of text blocks sets the order of the plain-text output and of the blocks in ALTO and
PAGE XML.

With `columns` (the default), printed horizontal rules, column gutters and full-width
headings divide the page, and each column is read top to bottom. A paragraph's last line that
the layout model split off is joined back to its paragraph. `basic` reads
horizontal bands left to right.

### Large text

With `TUZKAOCR_LARGE_TEXT=true` (the default), a page with text at least four times taller
than its body text, such as a newspaper masthead, gets one extra coarse layout pass, so the
title is read as one line instead of letter fragments. It costs 0.2–0.7 s on pages that need
it and nothing on the rest.

Reading order and large text apply to the printed domain only; the other domains use the
`basic` order without the large-text pass.

## Line roles

| Variable | Default | Effect |
|---|---|---|
| `TUZKAOCR_ROLE_CLASSIFIER` | `false` | Tag each ALTO line with a structural role |
| `TUZKAOCR_ROLE_MODEL` | `role-H5.onnx` | Bundled role classifier |

This is the server-wide default; the API's `role_classifier` form field and the CLI's
`--role-classifier` flag override it per request. See
[Output formats](output-formats.md#line-roles).

## ALTO output

| Variable | Default | Effect |
|---|---|---|
| `TUZKAOCR_ALTO_PROFILE` | `ndk` | `ndk` (Czech NDK ingest profile) or `basic` (simpler layout for existing consumers) |
| `TUZKAOCR_ALTO_AGENCY` | *empty* | Institution running the OCR, written as `processingAgency` |
| `TUZKAOCR_ALTO_LANG` | *empty* | Language code for `LANG`; empty means detect it from the text |
| `TUZKAOCR_ALTO_FONTFAMILY` | *empty* | Typeface written as `TextStyle/@FONTFAMILY` |
| `TUZKAOCR_ALTO_DPI` | `0` | Scan resolution used for `FONTSIZE`; `0` means read it from the image |
| `TUZKAOCR_ALTO_PAGE_WIDTH_MM` | `0` | Physical page width; the resolution is derived from it when the image records none |

`TUZKAOCR_ALTO_PROFILE` is the server-wide default; the API's `alto_profile` field and the
CLI's `--alto-profile` override it per request. The other variables affect only the `ndk`
profile.

Values TuzkaOCR cannot determine are left out rather than guessed. For NDK ingest, set
`TUZKAOCR_ALTO_AGENCY` (required), and set `TUZKAOCR_ALTO_DPI` or
`TUZKAOCR_ALTO_PAGE_WIDTH_MM` when your images record no resolution (common for derivative
JPEGs), so `FONTSIZE` can be written. See [Output formats](output-formats.md#styles).

The CLI flag `--ndk-warn` reports missing agency and page numbers during a run.

## Service limits and storage

| Variable | Default | Effect |
|---|---|---|
| `TUZKAOCR_RESULTS_DIR` | `results` | Where finished output is written |
| `TUZKAOCR_SPOOL_DIR` | *system temp* | Where uploads are streamed |
| `TUZKAOCR_MAX_JOB_AGE_HOURS` | `24` | Retention for jobs and result files |
| `TUZKAOCR_MAX_QUEUE` | `16` | Maximum queued + running jobs before 503 |
| `TUZKAOCR_MAX_UPLOAD_MB` | `256` | Request body limit; over this returns 413 |
| `TUZKAOCR_MAX_IMAGE_PIXELS` | `300000000` | Decoded pixel limit; over this fails the job with 422 |

The pixel limit applies to API jobs only. Uploads are streamed to the spool directory and
deleted after processing. A configured spool directory is cleared at startup, so do not share
one between instances, and keep it on real disk rather than `tmpfs`.

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
| `TUZKAOCR_OCR_MODEL` | `rec-E-v7.onnx` |
| `TUZKAOCR_KRAMARKY_LAYOUT_MODEL` | `dec-B-v1k.onnx` |
| `TUZKAOCR_KRAMARKY_OCR_MODEL` | `rec-E-v4k7.onnx` |
| `TUZKAOCR_HANDWRITTEN_LAYOUT_MODEL` | `dec-B-v2h.onnx` |
| `TUZKAOCR_HANDWRITTEN_OCR_MODEL` | `rec-I-v2.onnx` |
| `TUZKAOCR_KURRENT_LAYOUT_MODEL` | `dec-B-v2h.onnx` |
| `TUZKAOCR_KURRENT_OCR_MODEL` | `rec-I-v2.onnx` |
| `TUZKAOCR_VOCAB` | `vocab.json` |
| `TUZKAOCR_LANG_MODEL` | `lang-A-v1.npz` |

The defaults are the bundled files and normally need no change. See
[Models and domains](models.md) for how a name is resolved and when pinning makes sense.

## Custom domain packs

| Variable | Default | Effect |
|---|---|---|
| `TUZKAOCR_DOMAINS_DIR` | `$XDG_DATA_HOME/tuzkaocr/domains`, or `~/.local/share/tuzkaocr/domains` | Folder scanned for `.tpack` files and pack folders; Docker uses `/app/domains` |
| `TUZKAOCR_PACK_CACHE` | system temporary directory plus `tuzkaocr-packs/` | Writable cache for safely extracted `.tpack` files; Docker uses `/tmp/tuzkaocr-packs` |
| `TUZKAOCR_DEFAULT_DOMAIN` | The pack marked `default`, or built-in `print` | Select a loaded pack or built-in domain as the default; set to `print` to bypass a pack default |

Setting `TUZKAOCR_DOMAINS_DIR` to an empty string disables pack discovery. Pack settings are
overridden by explicitly set `TUZKAOCR_*` environment values, then by CLI flags or API form
fields where available. See [Custom domain packs](custom-domains.md) for installation and
validation.

## Memory

Peak memory is dominated by the layout model, about **1.3 GiB per page in flight**:

```
peak ≈ 0.1 GiB + PAGE_WORKERS × 1.3 GiB
```

By default (`TUZKAOCR_CPU_MEM_ARENA=true`) ONNX Runtime keeps its memory pool after a page,
so idle memory stays near the peak. Set it to `false` when memory is tight: memory is
released between pages, at some cost in single-page latency.

For tight limits, run one page worker per instance and scale out by instance count.
