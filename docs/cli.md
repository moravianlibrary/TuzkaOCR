# Command line

```
tuzkaocr <input> [options]
```

`<input>` is an image file, or a directory when `--batch` is given. Recognized extensions
in batch mode are `.jpg`, `.jpeg`, `.png`, `.tif`, and `.tiff`.

This page is the complete reference. For a guided first run that assumes no terminal
experience, see [Step by step, no experience needed](beginners.md).

After `pip install .` the `tuzkaocr` entry point is on `PATH`. From a checkout without
installing, use `python cli.py` in place of `tuzkaocr` in every example below.

## Single page

=== "ALTO XML"

    ```bash
    tuzkaocr page.jpg --out result.alto.xml
    ```

    ```
    Done in 2.4s — 412 words → result.alto.xml
    ```

=== "Plain text"

    ```bash
    tuzkaocr page.jpg --format txt --out result.txt
    ```

    ```
    Done in 2.3s — 37 lines → result.txt
    ```

=== "Both at once"

    ```bash
    tuzkaocr page.jpg --format multi --out page
    ```

    ```
    Done in 2.4s — 412 words, 37 lines → page.alto.xml, page.txt
    ```

    With `--format multi`, `--out` is a **stem** — the suffixes `.alto.xml` and `.txt` are
    appended. Both outputs come from a single OCR pass.

When `--out` is omitted, the output is written next to the input image with the suffix
replaced: `page.jpg` becomes `page.alto.xml`, `page.txt`, or both.

## Choosing a domain

`--domain` selects a matched layout and recognition model pair. This is the single setting
with the largest effect on output quality — see [Models and domains](models.md) for what
each pair was trained on.

```bash
tuzkaocr letter.jpg --domain handwritten --format txt --out letter.txt
```

| `--domain` | Material |
|---|---|
| `default`, `print` | Printed books and general scans |
| `kramarky` | Kramarky broadsheet prints (a narrow, specialised domain) |
| `handwritten` | Czech handwriting |
| `kurrent` | German Kurrent / Sütterlin script |

`handwritten` and `kurrent` additionally enable column-aware line ordering and extend line
crops at both ends, which suits free-flowing script.

## Batch processing

```bash
tuzkaocr input_pages/ \
  --batch \
  --format txt \
  --domain kramarky \
  --out-dir results/ \
  --workers 2
```

```
Processing 148 images with 2 worker(s)...
[   1/ 148] 0001.jpg 3.4s  ETA 4.2m
[   2/ 148] 0002.jpg 3.1s  ETA 4.0m
...
Done: 147/148 OK, 1 errors, total 268.1s (1.8s/page)
```

Outputs are named after each input's stem inside `--out-dir` (default `results`). Each
worker is a separate process that loads its own copy of the models, so memory scales with
`--workers` — budget roughly **1.3 GiB per worker**; see
[memory](configuration.md#memory).

A page that fails is reported on its own line and counted in the final summary; the batch
continues. The command exits non-zero only when the input directory contains no images.

## Options

### Input and output

| Option | Default | Effect |
|---|---|---|
| `--out` | *derived from input* | Output file for a single image; a stem when `--format multi` |
| `--out-dir` | `results` | Output directory in batch mode |
| `--format` | `alto` | `alto`, `txt`, or `multi` |
| `--batch` | off | Treat the input as a directory of images |

### Model selection

| Option | Default | Effect |
|---|---|---|
| `--domain` | `default` | Preset model pair: `default`, `print`, `kramarky`, `handwritten`, `kurrent` |
| `--layout-model` | *per domain* | Override the layout model, by bundled filename or path |
| `--ocr-model` | *per domain* | Override the recognition model, by bundled filename or path |
| `--vocab` | `vocab.json` | Override the recognizer character set |

`--layout-model` and `--ocr-model` override individual slots of the chosen `--domain`, so
you can swap one half of a pair. `--vocab` must match the recognizer in use.

### Performance

| Option | Default | Effect |
|---|---|---|
| `--workers` | `2` | Parallel page processes (batch mode only) |
| `--ocr-threads` | `4` | ONNX Runtime intra-op threads |
| `--line-workers` | `4` | Parallel line-recognition threads within one page |
| `--device` | `cpu` | `cpu`, `cuda`, or `auto` |

`--device auto` uses CUDA when `onnxruntime` reports a CUDA execution provider and falls
back to CPU otherwise. The plain `onnxruntime` wheel is CPU-only, so `auto` resolves to
`cpu` unless `onnxruntime-gpu` is installed.

### Quality

| Option | Default | Effect |
|---|---|---|
| `--height-scale` | `1.0` | Multiply predicted line heights; try `1.5` if crops clip ascenders |
| `--no-adaptive` | *adaptive on* | Force a single fixed-resolution layout pass |
| `--role-classifier` | off | Tag each line with a structural role in the ALTO output |

**Adaptive downsampling** is on by default. Each page is first processed at the standard
downsample; if it looks resolution-starved — overlapping baselines, or low recognition
confidence — it is reprocessed at a finer downsample and the result with the highest
confidence wins. Dense multi-column pages that escalate cost roughly 2–3× the per-page
time. `--no-adaptive` disables the second pass.

**Role classification** tags every line as `body`, `heading`, `header`, `footer`, or
`page_number`, surfaced in ALTO as a `StructureTag`. It costs a few milliseconds per page
and only affects `alto` and `multi` output. It prefers silence over wrong markup: when the
classifier is not confident, the line stays `body`, so mistakes appear as a missing tag
rather than an incorrect one. See [Output formats](output-formats.md#line-roles).

## Environment variables

Every default above comes from the configuration layer, so an environment variable changes
the default and the command-line flag overrides it for that invocation:

```bash
TUZKAOCR_OCR_THREADS=8 tuzkaocr page.jpg --out result.alto.xml
```

The full list is in [Configuration](configuration.md).
