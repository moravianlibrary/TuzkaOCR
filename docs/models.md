# Models and domains

Layout and recognition are two separate ONNX models, run by ONNX Runtime. A *domain* is a
matched pair of the two, plus the crop and line-ordering settings that suit that material.
Clients of the HTTP API choose a domain, never a model file.

## Domains

| Domain | Material | Layout | Recognition |
|---|---|---|---|
| `default` (also `print`) | Printed books and general scans | `dec-B-v2` | `rec-E-v5.int8` |
| `kramarky` | Kramarky broadsheet prints | `dec-B-v1k` | `rec-E-v4k7.int8` |
| `handwritten` | Czech handwriting | `dec-B-v2h` | `rec-H-v6.int8` |
| `kurrent` | German Kurrent / Sütterlin script | `dec-B-v2h` | `rec-H-v6.int8` |

`rec-H-v6` is a single general handwritten recognizer serving both `handwritten` and
`kurrent`; it supersedes the earlier Kurrent-only specialist.

`handwritten` and `kurrent` also extend line crops at both ends (0.3 of line height) and
order lines column-by-column within a region, which suits free-flowing script.

!!! warning "Kramarky is a narrow specialised domain"
    The kramarky pair is trained for kramarky broadsheet prints and should be selected only
    for that material. It is not a general periodical or newspaper model, and its results are
    not a meaningful benchmark of general OCR quality. For dense multi-column printed pages,
    use the printed domain and leave [adaptive
    downsampling](configuration.md#adaptive-downsampling) enabled.

Picking the domain is the highest-impact decision available to a caller — larger in effect
than any threading or quality flag.

## What ships in the package

Model files are installed as package data, so nothing is downloaded at first run.

| File | Size | Role |
|---|---|---|
| `dec-B-v2.onnx` | 10.6 MB | Layout, printed |
| `dec-B-v1k.onnx` | 10.6 MB | Layout, kramarky |
| `dec-B-v2h.onnx` | 10.6 MB | Layout, handwritten and Kurrent |
| `dec-A-v4.onnx`, `dec-A-v3k5.onnx` | 3.1 MB each | Earlier layout generation |
| `rec-E-v5.int8.onnx` | 3.2 MB | Recognition, printed |
| `rec-E-v4k7.int8.onnx` | 3.2 MB | Recognition, kramarky |
| `rec-H-v6.int8.onnx` | 12.4 MB | Recognition, handwritten and Kurrent |
| `rec-H-v4.int8.onnx` | 12.4 MB | Superseded handwritten recognizer |
| `rec-H-v3h-kurrent.int8.onnx` | 6.5 MB | Superseded Kurrent specialist |
| `role-H5.onnx` | 1.1 MB | Line role classifier |
| `vocab.json` | 888 B | Recognizer character set |

Recognizers are int8-quantized, which is what keeps a CPU deployment practical. The live
list for a running service is available from
[`GET /api/v1/models`](api.md#listing-models).

## How a model name is resolved

Each configured value is resolved in two steps:

1. If it names an existing file, that file is used. `~` is expanded.
2. Otherwise its **filename** is looked up in the bundled `tuzkaocr/models/` directory.

An unresolvable name fails at startup with a message listing everything bundled, rather
than failing on the first page.

```
Model 'rec-X-v9.onnx' not found on disk and not bundled in tuzkaocr.models
(bundled: ['dec-A-v3k5.onnx', 'dec-B-v2.onnx', ...])
```

This means a bundled file can be selected by bare filename, and a model outside the package
by absolute or relative path.

## Pinning a model

Superseded files stay bundled, so pinning an older model keeps working across upgrades. Set
the relevant variable from [Configuration](configuration.md#models):

```bash
TUZKAOCR_KURRENT_OCR_MODEL=rec-H-v3h-kurrent.int8.onnx
```

That restores the pre-`rec-H-v6` Kurrent specialist for the `kurrent` domain, leaving
`handwritten` on the current model.

On the CLI the equivalent is per-invocation, and can replace one half of a pair:

```bash
tuzkaocr page.jpg --domain kurrent --ocr-model rec-H-v3h-kurrent.int8.onnx
```

!!! danger "`vocab.json` is shared"
    One vocabulary serves every recognizer and must match the model in use. Override
    `TUZKAOCR_VOCAB` only alongside a custom recognizer that needs it — a mismatch produces
    confident nonsense rather than an error.

## Provenance in the output

Every ALTO file records which pair produced it, as two `OCRProcessing` elements — so a
downstream consumer can tell a `rec-E-v5` page from a `rec-H-v6` one years later without
external bookkeeping. See
[Output formats](output-formats.md#model-provenance).

## Licensing

The model artifacts are licensed separately from the code, under **CC BY-NC-SA 4.0** —
attribution, non-commercial, share-alike. The code is Apache 2.0. See
`tuzkaocr/models/LICENSE` in the repository. Commercial use of the models requires a separate
arrangement.
