# Command line

```
tuzkaocr <input> [options]
```

`<input>` is an image file, or a directory when `--batch` is given. Recognized extensions
in batch mode are `.jpg`, `.jpeg`, `.png`, `.tif`, and `.tiff`.

From a checkout without installing, use `python cli.py` in place of `tuzkaocr`.

The information flags do not need an input image:

```bash
tuzkaocr --version
tuzkaocr --list-domains
tuzkaocr --check-domains
```

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

=== "PAGE XML"

    ```bash
    tuzkaocr page.jpg --format page --out result.page.xml
    ```

    ```
    Done in 1.4s — 412 words → result.page.xml
    ```

=== "ALTO and text at once"

    ```bash
    tuzkaocr page.jpg --format multi --out page
    ```

    ```
    Done in 2.4s — 412 words, 37 lines → page.alto.xml, page.txt
    ```

    With `--format multi`, `--out` is a **stem** — the suffixes `.alto.xml` and `.txt` are
    appended. Both outputs come from a single OCR pass.

When `--out` is omitted, the output is written next to the input image with the suffix
replaced: `page.jpg` becomes `page.alto.xml`, `page.page.xml`, `page.txt`, or ALTO and text with
`multi`.

## Choosing a domain

`--domain` selects the model pair and matters more than any other setting — see
[Models and domains](models.md). Built-in and installed pack names are accepted. See
[Custom domain packs](custom-domains.md) for installation and version reporting.

```bash
tuzkaocr letter.jpg --domain handwritten --format txt --out letter.txt
```

| `--domain` | Material |
|---|---|
| `default`, `print` | Printed books and general scans |
| `kramarky` | Kramarky broadsheet prints (a narrow, specialised domain) |
| `handwritten` | Czech handwriting |
| `kurrent` | German Kurrent / Sütterlin script |
| `<pack-name>` | A loaded custom domain pack |

When a pack is marked as the default, `default` selects it. `print` and `printed` always
select the built-in print domain, so `--domain print` bypasses a default pack.

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

Outputs are named after each input's stem. Budget about **1.3 GiB per worker** (see
[memory](configuration.md#memory)). A failing page is reported and the batch continues.

## Options

### Input and output

| Option | Default | Effect |
|---|---|---|
| `--out` | *derived from input* | Output file for a single image; a stem when `--format multi` |
| `--out-dir` | `results` | Output directory in batch mode |
| `--format` | `alto` | `alto`, `page` (PAGE XML), `txt`, or `multi` (ALTO and text) |
| `--batch` | off | Treat the input as a directory of images |

### ALTO output

| Option | Default | Effect |
|---|---|---|
| `--alto-profile` | `ndk` | `ndk` (Czech NDK ingest profile) or `basic` (simpler layout for existing consumers) |
| `--alto-agency` | *unset* | Institution running the OCR, written as `processingAgency` |
| `--alto-lang` | *detected* | Force the `LANG` value |
| `--alto-dpi` | *from the image* | Force the resolution used for `FONTSIZE` |
| `--alto-page-width-mm` | *unset* | Physical page width; the resolution is derived from it when the image records none |
| `--source-identifier` | *none* | Identifier of the source image, written as `fileIdentifier` (single image only) |
| `--physical-img-nr` | *from the filename* | Page number within the volume, >=1 (single image only) |
| `--ndk-warn` | off | Report NDK fields that could not be filled |

```bash
tuzkaocr page.jpg --out result.alto.xml \
    --alto-agency "Moravian Library" \
    --source-identifier page-0007
```

None of these are needed for ordinary OCR. See [Configuration](configuration.md#alto-output).

### Model selection

| Option | Default | Effect |
|---|---|---|
| `--domain` | `default` | Built-in domain or loaded custom pack name; see [custom domain packs](custom-domains.md) |
| `--layout-model` | *per domain* | Override the layout model, by bundled filename or path |
| `--ocr-model` | *per domain* | Override the recognition model, by bundled filename or path |
| `--vocab` | `vocab.json` | Override the recognizer character set |

`--layout-model` and `--ocr-model` replace one half of the chosen domain's pair.

### Performance

| Option | Default | Effect |
|---|---|---|
| `--workers` | `2` | Parallel page processes (batch mode only) |
| `--ocr-threads` | `4` | ONNX Runtime intra-op threads |
| `--line-workers` | `4` | Parallel line-recognition threads within one page |
| `--device` | `cpu` | `cpu`, `cuda`, or `auto` |

`--device auto` uses CUDA only when `onnxruntime-gpu` is installed.

### Quality

| Option | Default | Effect |
|---|---|---|
| `--height-scale` | `TUZKAOCR_HEIGHT_SCALE` (`1.0`) | Multiply predicted line heights; try `1.5` if crops clip ascenders |
| `--no-adaptive` | `TUZKAOCR_ADAPTIVE_DOWNSAMPLE` (on) | Use the fixed layout downsample instead of sizing it to the page's text |
| `--reading-order` | `columns` | Block order on printed pages: `columns` or `basic` |
| `--no-large-text` | *large text on* | Skip the extra layout pass for mastheads and other very large text |
| `--role-classifier` | off | Tag each line with a structural role in the ALTO output |
| `--contrast` | `off` | `off`, `on`, `auto` or `line`; see [contrast normalisation](configuration.md#contrast-normalisation) |

`--no-adaptive`, `--reading-order` and `--no-large-text` affect the printed domain only; see
[Configuration](configuration.md#adaptive-downsampling). For roles see
[Output formats](output-formats.md#line-roles).

### Page orientation

| Option | Default | Effect |
|---|---|---|
| `--orientation` | `off` | `auto` rotates sideways and upside-down pages upright |
| `--orientation-threshold` | `0.9` | Below this classifier confidence, all four angles are tried |
| `--orientation-probe` | `on` | `off` trusts the classifier alone |

The CLI prints the chosen angle and method after each page. See
[page orientation](configuration.md#page-orientation).

## Environment variables

An environment variable sets the default; a flag overrides it for that run:

```bash
TUZKAOCR_OCR_THREADS=8 tuzkaocr page.jpg --out result.alto.xml
```

The full list is in [Configuration](configuration.md).

### Domain information

| Flag | Effect |
|---|---|
| `--version` | Show the core version and active default pack, if any |
| `--list-domains` | List built-in, loaded, and skipped domains |
| `--check-domains` | Validate pack manifests, checksums, recognizers, and vocabularies; exits non-zero for invalid packs |
