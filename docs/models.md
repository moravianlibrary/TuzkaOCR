# Models and domains

A *domain* is a layout model, a recognizer, and the settings that suit the material. API
clients choose a domain, never a model file.

## Domains

| Domain | Material | Layout | Recognition |
|---|---|---|---|
| `default` (also `print`) | Printed books and general scans | `dec-B-v2` | `rec-E-v7` |
| `kramarky` | Kramarky broadsheet prints | `dec-B-v1k` | `rec-E-v4k7` |
| `handwritten` | Czech handwriting and German Kurrent / Sütterlin script | `dec-B-v2h` | `rec-I-v2` |

Compared with `rec-E-v5`, `rec-E-v7` reads large display type, dark or coloured paper, faint
typewriting, carbon copies, dot-matrix print and one-line formulas better, and mostly
ignores ornaments and rules. It adds the Slovak letters `ľ ĺ ŕ ô` and common Greek
letters and symbols. `rec-E-v5` remains available by name.

`rec-I-v2` adapts to each writer: a small style model reads the whole page first, then each
line is recognized with that page style. Keep `rec-I-v2.onnx` and `rec-I-v2.style.onnx` in
the same directory; TuzkaOCR refuses to start without the style file.

!!! warning "Kramarky is a narrow domain"
    Use `kramarky` only for kramarky broadsheet prints. For newspapers and other printed
    pages, use the default domain.

Picking the right domain matters more than any other setting.

!!! note "`kurrent` was removed in 1.11.0"
    The `kurrent` domain used the same models and settings as `handwritten`, which reads
    Kurrent and Sütterlin, so it was removed. `--domain kurrent`, the API `domain=kurrent`,
    `TUZKAOCR_DEFAULT_DOMAIN=kurrent` and custom packs with `"base": "kurrent"` now fail with
    a message pointing to `handwritten`. `TUZKAOCR_KURRENT_LAYOUT_MODEL` and
    `TUZKAOCR_KURRENT_OCR_MODEL` are no longer read.

## What ships in the package

Model files are installed as package data, so nothing is downloaded at first run.

| File | Size | Role |
|---|---|---|
| `dec-B-v2.onnx` | 10.6 MB | Layout, printed |
| `dec-B-v1k.onnx` | 10.6 MB | Layout, kramarky |
| `dec-B-v2h.onnx` | 10.6 MB | Layout, handwritten |
| `rec-E-v7.onnx` | 3.2 MB | Recognition, printed |
| `rec-E-v5.onnx` | 3.2 MB | Older printed recognizer, selectable by name |
| `rec-E-v4k7.onnx` | 3.2 MB | Recognition, kramarky |
| `rec-I-v2.onnx` | 12.6 MB | Recognition, handwritten |
| `rec-I-v2.style.onnx` | 0.3 MB | Page style, used with `rec-I-v2.onnx` |
| `rec-H-v6.onnx` | 12.4 MB | Older handwritten recognizer, selectable by name |
| `role-H5.onnx` | 1.1 MB | Line role classifier |
| `orient-A.onnx` | 1.2 MB | Page orientation |
| `vocab.json` | 1.4 KB | Shared, append-only recognizer vocabulary with 233 characters |
| `lang-A-v1.npz` | 45 KB | Language identification for ALTO `LANG` |

## Language identification

`lang-A-v1.npz` detects Czech, German, English, Slovak, Polish and Latin for ALTO `LANG` — see
[Output formats → Language](output-formats.md#language).

## How a model name is resolved

A value that names an existing file is used as given; otherwise its filename is looked up in
the bundled `tuzkaocr/models/`. Custom pack model paths resolve inside the pack. An
unresolvable name fails at startup.

## Pinning a model

To use a different model for a domain, set its [model variable](configuration.md#models)
on the server, for example `TUZKAOCR_HANDWRITTEN_OCR_MODEL=/models/my-recognizer.onnx`, or
pass `--layout-model` / `--ocr-model` on the CLI.

`vocab.json` is shared by the bundled recognizers. A custom recognizer always comes with its
own matching vocabulary; if the model expects more output classes than the vocabulary covers,
startup reports the class-count mismatch instead of failing later during decoding. When using
`--ocr-model` directly, pass its matching `--vocab` as well.

To distribute your own model as a single file, use a [custom domain pack](custom-domains.md). It keeps
the recognizer, vocabulary, checksums, and domain settings together.

Every ALTO file names the layout and recognition models that produced it — see
[Output formats](output-formats.md#model-provenance).

## Licensing

The models are licensed under **CC BY-NC-SA 4.0** (non-commercial); the code under Apache 2.0.
Commercial use of the models requires a separate arrangement.
