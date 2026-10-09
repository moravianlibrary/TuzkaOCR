# Output formats

Four formats, chosen with `--format` on the CLI or the `fmt` field on the API: `alto`,
`page`, `txt`, and `multi`.

## Plain text

One line of recognized text per detected line, in reading order, UTF-8 encoded. No
coordinates, no confidence, no structure. Blocks are separated by a blank line.

```
KRAMARSKA PISEN
o velike vode v Brne
leta Pane 1893
```

Best for full-text indexing and search. Use ALTO or PAGE if you need to link text back to the
image.

A word broken across a line end keeps its hyphen and line break here; ALTO also records the
rejoined word — see [Hyphenation](#hyphenation).

## ALTO XML

[ALTO](https://www.loc.gov/standards/alto/) 4, declaring schema version 4.4. All coordinates
are in **pixels** of the source image and every rectangle is clipped to the page bounds.

### Profiles

Selected with `--alto-profile` (CLI), the `alto_profile` form field (API), or
`TUZKAOCR_ALTO_PROFILE` server-wide. An unknown value is rejected.

| Profile | What it is |
|---|---|
| `ndk` **(default)** | Output aimed at the Czech NDK ingest profile: `Processing` provenance, source image information, `Styles`, the four page margins, `LANG`, word and character confidence, hyphenation, `SP` with coordinates. Choosing it does not by itself make a file NDK-compliant — see [Configuration](configuration.md#alto-output) and the [remaining limitations](#ndk-profile-remaining-limitations). |
| `basic` | The pre-1.7.2 shape, for consumers written against it: `OCRProcessing` provenance, `PrintSpace` covering the whole page, bare `<SP/>`, positional identifiers, `PHYSICAL_IMG_NR="1"` unless given explicitly. |

### Structure

The `ndk` profile:

```
alto SCHEMAVERSION="4.4"
├── Description
│   ├── MeasurementUnit                pixel
│   ├── sourceImageInformation
│   │   ├── fileName                   the source image filename
│   │   └── fileIdentifier             only when a source identifier is given
│   ├── Processing ID="IdPreOperation" only when the image was downsampled for layout
│   ├── Processing ID="IdLayout"
│   └── Processing ID="IdRecognition"
├── Styles
│   ├── TextStyle ID="TS1" [FONTFAMILY] FONTSIZE   only when the resolution is known
│   └── ParagraphStyle ID="PS_Left" ALIGN="Left"
├── Tags                               only when roles are enabled
└── Layout
    └── Page ID="P1" WIDTH HEIGHT PHYSICAL_IMG_NR [LANG] ACCURACY PC
        ├── TopMargin    ID="P1_TM0001" HPOS VPOS WIDTH HEIGHT
        ├── LeftMargin   ID="P1_LM0001" …
        ├── RightMargin  ID="P1_RM0001" …
        ├── BottomMargin ID="P1_BM0001" …
        └── PrintSpace   ID="P1_PS0001" HPOS VPOS WIDTH HEIGHT
            └── TextBlock ID="P1_TB0001" STYLEREFS HPOS VPOS WIDTH HEIGHT [LANG]
                ├── Shape → Polygon POINTS      the detected region outline
                └── TextLine ID="P1_TL0001" STYLEREFS HPOS VPOS WIDTH HEIGHT [LANG TAGREFS]
                    ├── String ID="P1_ST0001" CONTENT HPOS VPOS WIDTH HEIGHT
                    │          [WC CC LANG SUBS_TYPE SUBS_CONTENT]
                    ├── SP ID="P1_SP0001" HPOS VPOS WIDTH
                    └── HYP CONTENT [HPOS VPOS WIDTH]   at most one, last in the line
```

The `basic` profile:

```
alto SCHEMAVERSION="4.4"
├── Description
│   ├── MeasurementUnit                pixel
│   ├── OCRProcessing ID="IdLayout"
│   └── OCRProcessing ID="IdRecognition"
├── Tags                               only when roles are enabled
└── Layout
    └── Page ID="page_<stem>" WIDTH HEIGHT PHYSICAL_IMG_NR
        └── PrintSpace                 the whole page
            └── TextBlock ID="block_0"
                └── TextLine ID="line_0_0" [TAGREFS]
                    ├── String ID="word_0_0_0" CONTENT HPOS VPOS WIDTH HEIGHT
                    └── SP
```

In `ndk` all identifiers are page-sequential (`P1_TB0001`, `P1_TL0001`, `P1_ST0001`,
`P1_SP0001`); in `basic` they are positional (`block_<b>`, `line_<b>_<l>`, `word_<b>_<l>_<w>`).
If your code matches the `basic` identifiers, pin `--alto-profile basic`.

A `TextBlock`'s rectangle is the bounding box of its lines. Lines with no recognized text are
dropped.

### Page number

`Page/@PHYSICAL_IMG_NR` is the page's sequential number within the volume, and ALTO requires
it. In the `ndk` profile it comes from, in order:

1. `--physical-img-nr` (CLI) or the `physical_img_nr` form field (API).
2. A trailing number of at most five digits in the source filename: `pr_0007.jp2` → 7,
   `123456_006.tif` → 6. Names like `IMG_20240115.jpg` or `0007_recto.jp2` are not used.
3. `1`.

If you prepare material for ingest and your filenames carry no page number, pass it
explicitly; `--ndk-warn` reports pages that fell back to `1`.

### Print space and margins

`PrintSpace` is the bounding box of the body text; the four margins are the strips around it
and are always present, zero-sized when the text reaches that edge.

With [role classification](#line-roles) enabled, blocks that are mostly `header` lines move
into `TopMargin`, and mostly `footer` or `page_number` lines into `BottomMargin` — but only if
they sit clear of the body text. Without roles, every block stays in the print space.

### Model provenance

Each `Processing` element records one stage: `IdPreOperation` (the downsampling factor used
for layout analysis), `IdLayout` and `IdRecognition`, with the package version and the model
name:

```xml
<Processing ID="IdRecognition">
  <processingCategory>contentGeneration</processingCategory>
  <processingDateTime>2026-09-03T07:55:26+00:00</processingDateTime>
  <processingAgency>Moravian Library</processingAgency>
  <processingStepDescription>recognition</processingStepDescription>
  <processingSoftware>
    <softwareCreator>tuzkaocr</softwareCreator>
    <softwareName>TuzkaOCR</softwareName>
    <softwareVersion>1.8.0</softwareVersion>
    <applicationDescription>recognition model rec-E-v5</applicationDescription>
  </processingSoftware>
</Processing>
```

Use `processingStepDescription` to tell the stages apart. The model pair identifies the domain:
`dec-B-v2` + `rec-E-v5` is printed, `dec-B-v1k` + `rec-E-v4k7` is kramarky,
`dec-B-v2h` + `rec-I-v2` is handwritten or Kurrent.

`processingAgency` is written only when `TUZKAOCR_ALTO_AGENCY` (or `--alto-agency`) is set.
NDK ingest requires it.

The `basic` profile writes two `OCRProcessing` elements instead, with the model file stem as
`softwareName`.

### Confidence

| Attribute | Where | Scale |
|---|---|---|
| `WC` | `String` | 0 = uncertain … 1 = certain |
| `CC` | `String` | one digit per character of `CONTENT`, **0 = certain … 9 = uncertain** |
| `ACCURACY` | `Page` | 0–100 |
| `PC` | `Page` | 0–1 |

All four come from the recognizer's per-character probabilities. The page value is the mean
line confidence. It is a model confidence, **not** a measured accuracy.

### Hyphenation

A word broken across a line end within one text block is recorded as two fragments plus the
whole word:

```xml
<String CONTENT="roz" … SUBS_TYPE="HypPart1" SUBS_CONTENT="rozhodnutí"/>
<HYP CONTENT="-" …/>
</TextLine>
<TextLine …>
  <String CONTENT="hodnutí" … SUBS_TYPE="HypPart2" SUBS_CONTENT="rozhodnutí"/>
```

The recognized break characters are `-`, `‐`, `‑`, soft hyphen, `¬`, `=` and `⸗`. The hyphen
is kept in `SUBS_CONTENT` when the next fragment starts with a capital or either side is a
digit (`1848-` + `1849` → `1848-1849`), and dropped otherwise. A lowercase compound broken at
its own hyphen (`česko-` + `slovenský`) is therefore joined without it.

A hyphen with no continuation — the last line of a block, or a word split over three or more
lines — stays inside `CONTENT` with no substitution. Plain text output always keeps the
original line breaks and hyphens.

### Styles

`ParagraphStyle/@ALIGN` (`Left`, `Right`, `Center`, `Block`) is measured from each block's
line edges.

`FONTSIZE` is estimated from line geometry and the scan resolution:

```
FONTSIZE = min(line_height_px, line_pitch_px) × 72 / dpi
```

One `TextStyle` is emitted per rounded point size, largest first, so `TS1` is the largest
type. The resolution is taken from, in order: `TUZKAOCR_ALTO_DPI`, the image file itself (JPEG,
PNG or TIFF metadata), and `TUZKAOCR_ALTO_PAGE_WIDTH_MM`. Declared resolutions below 100 dpi —
typically the 72 or 96 dpi default written by image software — are ignored. With no
resolution, no `TextStyle` is written and `STYLEREFS` points at the paragraph style only.

`FONTFAMILY` is written only when `TUZKAOCR_ALTO_FONTFAMILY` is set.

### Language

In the `ndk` profile, `LANG` is detected from the recognized text of the page by the bundled
`lang-A-v1` model (see [Models](models.md#language-identification)): Czech, German, English,
Slovak, Polish or Latin, as ISO 639-1 codes. One language is chosen per page and written on
`Page`, `TextBlock`, `TextLine` and `String`.

`LANG` is omitted when the page is in another language or has too little text (fewer than 25
words, or fewer than 8 distinct ones). Set `TUZKAOCR_ALTO_LANG` (or `--alto-lang`) to force a
value instead.

On 254 historical printed pages the detector labelled 95.7% and was right on 95.1% of those.

### Line roles

With role classification enabled, each line is tagged `body`, `heading`, `header`, `footer`,
or `page_number`. Roles surface as `StructureTag` elements in a top-level `<Tags>` block,
referenced from each `TextLine` by `TAGREFS`:

```xml
<Tags>
  <StructureTag ID="ROLE_heading" LABEL="heading"/>
</Tags>
...
<TextLine ID="P1_TL0001" … TAGREFS="ROLE_heading">
  <String ID="P1_ST0001" CONTENT="KRAMARSKA" …/>
  <SP ID="P1_SP0001" …/>
  <String ID="P1_ST0002" CONTENT="PISEN" …/>
</TextLine>
```

Two things to expect when parsing:

- **`body` is never tagged.** Only non-body roles get a `StructureTag`, and `<Tags>` is
  omitted entirely when a page has none. An untagged line means `body`.
- **A missing tag is not an error.** The classifier prefers silence to wrong markup: when it
  is not confident, the line stays `body`. Mistakes appear as absent roles, never incorrect
  ones.

In the `ndk` profile roles additionally drive [margin placement](#print-space-and-margins).

Enable it per request with `--role-classifier` (CLI) or `role_classifier=true` (API), or
server-wide with `TUZKAOCR_ROLE_CLASSIFIER=true`. Roles affect only `alto`, `page` and
`multi` output — plain text has nowhere to put them. For PAGE see
[Roles and region types](#roles-and-region-types).

### NDK profile: remaining limitations

These NDK requirements are not produced by TuzkaOCR:

- **`ComposedBlock`, `Illustration`, `GraphicalElement`** — only text is detected. A page that
  is only an illustration gets an empty `PrintSpace`.
- **`FONTSTYLE`** — bold, italic and small caps are not detected.
- **`ALTERNATIVE`** — no alternative readings are produced.
- **`ROTATION`, `POSITION`, `QUALITY` on `Page`** — not detected.
- **`StructureTag/@TYPE`** — line roles have no controlled vocabulary; only `ID` and `LABEL`
  are written.
- **`TextBlock` in `LeftMargin` / `RightMargin`** — marginalia stay in the print space.

These are written only when configured or detectable: `processingAgency`, `FONTFAMILY`,
`FONTSIZE` (needs a resolution), `LANG` and `PHYSICAL_IMG_NR` — see
[Configuration](configuration.md#alto-output).

## PAGE XML

[PAGE](https://github.com/PRImA-Research-Lab/PAGE-XML) in the 2019-07-15 schema, the format
read by Transkribus, eScriptorium, Kraken and OCR-D tools. All coordinates are in **pixels**
of the source image and every point is clipped to the page. The output validates against
the official `pagecontent.xsd`.

Unlike ALTO, PAGE keeps the detected line geometry: each `TextLine` carries its baseline and
the oriented quadrilateral it was read from, so skewed and curved lines survive a round trip
into a correction tool. The `--alto-*` options and `alto_profile` have no effect on it.

### Structure

```
PcGts
├── Metadata
│   ├── Creator                        TuzkaOCR <version>
│   ├── Created / LastChange
│   ├── MetadataItem type="processingStep" name="layout"       value=<layout model>
│   └── MetadataItem type="processingStep" name="recognition"  value=<recognition model>
└── Page imageFilename imageWidth imageHeight [primaryLanguage]
    ├── ReadingOrder → OrderedGroup → RegionRefIndexed index regionRef
    └── TextRegion id="r0001" type custom="readingOrder {index:0;}"
        ├── Coords points                  the detected region outline
        ├── TextLine id="r0001_l0001" custom="readingOrder {index:0;}"
        │   ├── Coords points              the line quadrilateral
        │   ├── Baseline points            the detected baseline
        │   ├── Word id="r0001_l0001_w0001"
        │   │   ├── Coords points          the word rectangle
        │   │   └── TextEquiv conf → Unicode
        │   └── TextEquiv conf → Unicode   the line text
        └── TextEquiv → Unicode            the region's lines joined by newlines
```

Regions appear in reading order, which `ReadingOrder` also states explicitly. Lines with no
recognized text are dropped, and a region left with no lines is omitted.

`conf` is the recognizer's confidence, 0 = uncertain … 1 = certain — the same values as ALTO
`WC`. The line confidence is the one averaged into `mean_conf`. PAGE has no per-character
confidence and no hyphenation markup: a word broken across a line end stays as two words with
the hyphen, as in plain text.

`primaryLanguage` comes from the same detector as ALTO `LANG` — see [Language](#language) —
written as the PAGE language name (`Czech`, `German`, `English`, `Slovak`, `Polish`,
`Latin`). `TUZKAOCR_ALTO_LANG` overrides it too.

### Roles and region types

With [role classification](#line-roles) enabled, a region's `type` is the dominant role of
its lines — `heading`, `header`, `footer`, or `page-number` — and `paragraph` otherwise.
Each non-body line also carries it in the Transkribus-style `custom` attribute:

```xml
<TextLine id="r0001_l0001" custom="readingOrder {index:0;} structure {type:heading;}">
```

Without roles every region is `paragraph`.

## Both at once

`multi` produces ALTO and text from a **single OCR pass**, so it costs the same as either one
alone. Use it whenever you want both; running the page twice is pure waste. PAGE XML is not
part of `multi`; request it with `page`.

On the CLI, `--out` becomes a stem and both suffixes are appended:

```bash
tuzkaocr page.jpg --format multi --out page
```

```
Done in 2.4s — 412 words, 37 lines → page.alto.xml, page.txt
```

On the API, one job holds both results and `?which=alto|txt` selects at download time,
defaulting to `alto`. See [Getting both formats](api.md#getting-both-formats).
