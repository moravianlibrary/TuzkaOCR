# Output formats

Three formats, chosen with `--format` on the CLI or the `fmt` field on the API: `alto`,
`txt`, and `multi`.

## Plain text

One line of recognized text per detected line, in reading order, UTF-8 encoded. No
coordinates, no confidence, no structure. Blocks are separated by a blank line.

```
KRAMARSKA PISEN
o velike vode v Brne
leta Pane 1893
```

Best for full-text indexing and search. Use ALTO if you need to link text back to the image.

## ALTO XML

[ALTO](https://www.loc.gov/standards/alto/) 4 with word-level bounding boxes, declaring
schema version 4.4:

```xml
<alto xmlns="http://www.loc.gov/standards/alto/ns-v4#"
      xsi:schemaLocation="http://www.loc.gov/standards/alto/ns-v4#
                          http://www.loc.gov/standards/alto/v4/alto-4-4.xsd">
```

All coordinates are in **pixels** of the source image, as declared by
`<MeasurementUnit>pixel</MeasurementUnit>`, and every rectangle is clipped to the page
bounds, so no box can extend outside the image.

### Structure

```
alto
├── Description
│   ├── MeasurementUnit            pixel
│   ├── OCRProcessing ID="IdLayout"
│   └── OCRProcessing ID="IdRecognition"
├── Tags                           only when roles are enabled
│   └── StructureTag ID="ROLE_heading" LABEL="heading"
└── Layout
    └── Page ID="page_<stem>" WIDTH HEIGHT PHYSICAL_IMG_NR="1"
        └── PrintSpace
            └── TextBlock ID="block_0"
                └── TextLine ID="line_0_0" [TAGREFS]
                    ├── String ID="word_0_0_0" CONTENT HPOS VPOS WIDTH HEIGHT
                    └── SP
```

Identifiers are positional and stable within a file: `block_<b>`, `line_<b>_<l>`,
`word_<b>_<l>_<w>`. The page ID derives from the input filename stem, sanitized to a valid
XML name. `<SP>` separates words within a line but never trails the last one.

A `TextBlock`'s rectangle is the bounding box of its lines, not an independently predicted
region.

### Model provenance

Two `OCRProcessing` elements record the pair that produced the file — layout and
recognition, each with its own timestamp and model name:

```xml
<OCRProcessing ID="IdLayout">
  <ocrProcessingStep>
    <processingDateTime>2026-08-31T13:12:53.645851+00:00</processingDateTime>
    <processingStepDescription>layout</processingStepDescription>
    <processingSoftware>
      <softwareCreator>tuzkaocr</softwareCreator>
      <softwareName>dec-B-v2</softwareName>
    </processingSoftware>
  </ocrProcessingStep>
</OCRProcessing>
<OCRProcessing ID="IdRecognition">
  <ocrProcessingStep>
    <processingDateTime>2026-08-31T13:12:53.645851+00:00</processingDateTime>
    <processingStepDescription>recognition</processingStepDescription>
    <processingSoftware>
      <softwareCreator>tuzkaocr</softwareCreator>
      <softwareName>rec-E-v5.int8</softwareName>
    </processingSoftware>
  </ocrProcessingStep>
</OCRProcessing>
```

Read `processingStepDescription` to tell the two apart rather than relying on document order.
The pair identifies the domain: `dec-B-v2` + `rec-E-v5.int8` is printed, `dec-B-v1k` +
`rec-E-v4k7.int8` is kramarky, `dec-B-v2h` + `rec-H-v6.int8` is handwritten or Kurrent.

### Line roles

With role classification enabled, each line is tagged `body`, `heading`, `header`, `footer`,
or `page_number`. Roles surface as `StructureTag` elements in a top-level `<Tags>` block,
referenced from each `TextLine` by `TAGREFS`:

```xml
<Tags>
  <StructureTag ID="ROLE_heading" LABEL="heading"/>
</Tags>
...
<TextLine ID="line_0_0" HPOS="112" VPOS="100" WIDTH="430" HEIGHT="51" TAGREFS="ROLE_heading">
  <String ID="word_0_0_0" CONTENT="KRAMARSKA" HPOS="120" VPOS="100" WIDTH="323" HEIGHT="51"/>
  <SP/>
  <String ID="word_0_0_1" CONTENT="PISEN" HPOS="445" VPOS="100" WIDTH="235" HEIGHT="51"/>
</TextLine>
```

Two things to expect when parsing:

- **`body` is never tagged.** Only non-body roles get a `StructureTag`, and `<Tags>` is
  omitted entirely when a page has none. An untagged line means `body`.
- **A missing tag is not an error.** The classifier prefers silence to wrong markup: when it
  is not confident, the line stays `body`. Mistakes appear as absent roles, never incorrect
  ones.

Enable it per request with `--role-classifier` (CLI) or `role_classifier=true` (API), or
server-wide with `TUZKAOCR_ROLE_CLASSIFIER=true`. Roles affect only `alto` and `multi`
output — plain text has nowhere to put them.

## Both at once

`multi` produces ALTO and text from a **single OCR pass**, so it costs the same as either one
alone. Use it whenever you want both; running the page twice is pure waste.

On the CLI, `--out` becomes a stem and both suffixes are appended:

```bash
tuzkaocr page.jpg --format multi --out page
```

```
Done in 2.4s — 412 words, 37 lines → page.alto.xml, page.txt
```

On the API, one job holds both results and `?which=alto|txt` selects at download time,
defaulting to `alto`. See [Getting both formats](api.md#getting-both-formats).
