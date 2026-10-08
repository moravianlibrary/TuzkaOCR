# Models and domains

Each domain pairs a layout model with a recognizer, and ONNX Runtime runs the models.
Handwritten recognition uses both a recognition model and a small style model, so its
recognizer ships as two ONNX files. A *domain* is the model pair plus the crop and
line-ordering settings that suit the material. Clients of the HTTP API choose a domain,
never a model file.

## Domains

| Domain | Material | Layout | Recognition |
|---|---|---|---|
| `default` (also `print`) | Printed books and general scans | `dec-B-v2` | `rec-E-v5` |
| `kramarky` | Kramarky broadsheet prints | `dec-B-v1k` | `rec-E-v4k7` |
| `handwritten` | Czech handwriting | `dec-B-v2h` | `rec-I-v2` |
| `kurrent` | German Kurrent / Sütterlin script | `dec-B-v2h` | `rec-I-v2` |

`rec-I-v2` is the general handwritten recognizer for both `handwritten` and `kurrent`. It
adapts to each writer: a small style model reads all lines of the page first, then the
recognizer reads each line with that page-level style. It ships as
`rec-I-v2.onnx` and `rec-I-v2.style.onnx`; keep both files together in the same
directory. TuzkaOCR finds the style file by name and refuses to start without it. A
single-line page is read without page context.

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
| `rec-E-v5.onnx` | 3.2 MB | Recognition, printed |
| `rec-E-v4k7.onnx` | 3.2 MB | Recognition, kramarky |
| `rec-I-v2.onnx` | 12.6 MB | Recognition, handwritten and Kurrent |
| `rec-I-v2.style.onnx` | 0.3 MB | Page style, used with `rec-I-v2.onnx` |
| `rec-H-v6.onnx` | 12.4 MB | Previous handwritten recognizer, kept for pinning |
| `role-H5.onnx` | 1.1 MB | Line role classifier |
| `vocab.json` | 1.2 KB | Shared, append-only recognizer vocabulary with 203 characters |
| `lang-A-v1.npz` | 45 KB | Language identification for ALTO `LANG` |

The live list of selectable models for a running service is available from
[`GET /api/v1/models`](api.md#listing-models).

## Language identification

`lang-A-v1.npz` sets the ALTO `LANG` attributes in the `ndk` profile. It is a small NumPy
classifier over the recognized text, covering Czech, German,
English, Slovak, Polish and Latin; text in other languages is declined and gets no `LANG`.
One detector serves every domain. Replace it with `TUZKAOCR_LANG_MODEL`, or override its output
with `TUZKAOCR_ALTO_LANG`. See [Output formats → Language](output-formats.md#language).

## How a model name is resolved

Each configured value is resolved in two steps:

1. If it names an existing file, that file is used. `~` is expanded.
2. Otherwise its **filename** is looked up in the bundled `tuzkaocr/models/` directory.

An unresolvable name fails at startup with a message listing everything bundled, rather
than failing on the first page.

```
Model 'rec-X-v9.onnx' not found on disk and not bundled in tuzkaocr.models
(bundled: ['dec-B-v1k.onnx', 'dec-B-v2.onnx', ...])
```

This means a bundled file can be selected by bare filename, and a model outside the package
by absolute or relative path.

## Pinning a model

The previous handwritten recognizer stays bundled, so pinning it keeps working across this
upgrade. Set the relevant variables from [Configuration](configuration.md#models):

```bash
TUZKAOCR_HANDWRITTEN_OCR_MODEL=rec-H-v6.onnx
TUZKAOCR_KURRENT_OCR_MODEL=rec-H-v6.onnx
```

That restores the previous handwritten model for both domains.

On the CLI the equivalent is per-invocation, and can replace one half of a pair:

```bash
tuzkaocr page.jpg --domain kurrent --ocr-model rec-H-v6.onnx
```

!!! warning "`vocab.json` is shared"
    The vocabulary is an append-only superset that decodes every bundled recognizer. A
    custom vocabulary must still match the model in use; `rec-I-v2` requires all 203
    characters. Override `TUZKAOCR_VOCAB` only alongside a custom recognizer that needs it.

## Provenance in the output

Every ALTO file records which pair produced it, as two `Processing` elements — one for
layout, one for recognition, each naming the model in `applicationDescription` — so a
downstream consumer can tell a `rec-E-v5` page from a `rec-I-v2` one years later without
external bookkeeping. The legacy `basic` profile writes the same information as two
deprecated `OCRProcessing` elements instead. See
[Output formats](output-formats.md#model-provenance).

## Licensing

The model artifacts are licensed separately from the code, under **CC BY-NC-SA 4.0** —
attribution, non-commercial, share-alike. The code is Apache 2.0. See
`tuzkaocr/models/LICENSE` in the repository. Commercial use of the models requires a separate
arrangement.
