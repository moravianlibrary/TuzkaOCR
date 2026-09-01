# Installation

!!! tip "Not comfortable with a terminal?"
    [Step by step, no experience needed](beginners.md) covers the same ground for
    readers who have never used a command line — no git, per-platform instructions,
    and a plain-language version of what each line does.

## Requirements

| | |
|---|---|
| Python | 3.10 or newer |
| Disk | ~1.5 GB for dependencies, plus ~80 MB of bundled models |
| Hardware | Any x86-64 or ARM64 CPU; no GPU needed |
| Network | None at runtime — models ship inside the package |

Dependencies are version-pinned (NumPy 2.1, ONNX Runtime 1.25, OpenCV 4.10, SciPy 1.14),
so install into a virtual environment rather than a system Python.

### Platform support

Linux, Windows, and Apple Silicon macOS are supported.

!!! warning "Intel Macs are not supported"
    Upstream `onnxruntime` no longer publishes x86-64 macOS wheels — 1.18 and later are
    arm64-only — so `pip install` fails on Intel hardware. Use the
    [Docker CPU image](docker.md) instead.

## Install from a checkout

There is no PyPI release; you install from a clone of the repository.

```bash
git clone https://github.com/moravianlibrary/TuzkaOCR.git
cd TuzkaOCR
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install .
```

Releases are tagged, so pin a known version rather than tracking `main` when reproducibility
matters:

```bash
git checkout v1.7.1        # or any tag listed on the releases page
pip install --force-reinstall --no-deps .
```

The [releases page](https://github.com/moravianlibrary/TuzkaOCR/releases) lists every
published version with its notes.

This puts the `tuzkaocr` command on your `PATH` and installs the layout and recognition
models as package data, so nothing is downloaded on first run.

### Verify

```console
$ tuzkaocr --help
usage: tuzkaocr [-h] [--out OUT] [--out-dir OUT_DIR]
                [--format {alto,txt,multi}] [--batch] ...
```

If the option list prints, the models resolved and ONNX Runtime loaded.

Then OCR a real page:

```console
$ tuzkaocr page.jpg --format txt --out page.txt
Done in 2.4s — 37 lines → page.txt
```

## Running without installing

Every command also works from the repository root as `python cli.py …`, once the
dependencies are present:

```bash
pip install -r requirements.txt
python cli.py page.jpg --out result.alto.xml
```

This is also the only mode in which the `tuzkaocr.env` file is picked up — see
[Configuration](configuration.md#where-settings-come-from).

## Upgrading

`pip install .` is a no-op when the version in `pyproject.toml` has not changed, so after
pulling new commits it can silently leave the old code and models in place. Force it:

```bash
git pull
pip install --force-reinstall --no-deps .
pip show tuzkaocr | head -2
```

Check that the reported version matches `pyproject.toml`. A stale install is the usual
reason a newly added model or environment variable appears to be missing.

## Development install

To have code edits take effect without reinstalling:

```bash
pip install -e .
```

Model files are read from the source tree in this mode, so dropping a new `.onnx` into
`tuzkaocr/models/` makes it immediately resolvable by name.
