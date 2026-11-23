# Installation

!!! tip "Not comfortable with a terminal?"
    [Step by step, no experience needed](beginners.md) covers the same ground for
    readers who have never used a command line — no git, per-platform instructions,
    and a plain-language version of what each line does.

## Requirements

| | |
|---|---|
| Python | 3.11 to 3.14 (3.15 is not supported yet — no `onnxruntime` build exists for it) |
| Disk | ~1.5 GB for dependencies, plus ~80 MB of bundled models |
| Hardware | Any x86-64 or ARM64 CPU; no GPU needed |
| Network | None at runtime — models ship inside the package |

Install into a virtual environment. `onnxruntime` and `opencv-python-headless` are pinned
exactly because they determine the OCR output; `numpy`, `scipy` and `pyyaml` follow your
Python version. `requirements.txt` pins the exact set the Docker image is built with,
which installs on Python 3.11 to 3.13.

### Platform support

Linux, Windows, and Apple Silicon macOS are supported.

!!! warning "Intel Macs are not supported"
    Upstream `onnxruntime` no longer publishes x86-64 macOS wheels — 1.18 and later are
    arm64-only — so `pip install` fails on Intel hardware. Use the
    [Docker CPU image](docker.md) instead.

## Install with uv

The simplest way. One line installs [uv](https://docs.astral.sh/uv/) if it is missing, then
the newest release with a supported Python, and puts `tuzkaocr` on your `PATH` — no virtual
environment to activate:

```bash
curl -LsSf https://moravianlibrary.github.io/TuzkaOCR/install.sh | sh
```

On Windows:

```bat
powershell -ExecutionPolicy ByPass -c "irm https://moravianlibrary.github.io/TuzkaOCR/install.ps1 | iex"
```

Open a new terminal afterwards. Rerunning the line upgrades to the newest release; set
`TUZKAOCR_VERSION=v1.10.1` first to install a specific tag. The scripts
([`install.sh`](install.sh), [`install.ps1`](install.ps1)) only wrap uv; by hand:

```bash
uv tool install --force --python 3.13 https://github.com/moravianlibrary/TuzkaOCR/archive/refs/tags/v1.10.1.zip
```

Keep `--python`: uv otherwise picks the newest Python, which may not be supported. On
Windows the script requests the x86-64 Python (`cpython-3.13-windows-x86_64-none`), so
ARM64 Windows runs it under emulation. [Step by step](beginners.md) walks through the same
for newcomers.

## Install from a checkout

There is no PyPI release; you install from a clone of the repository.

```bash
git clone https://github.com/moravianlibrary/TuzkaOCR.git
cd TuzkaOCR
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install .
```

This puts `tuzkaocr` on your `PATH`; the models are bundled, so nothing is downloaded at run
time. To pin a version, `git checkout` a tag from the
[releases page](https://github.com/moravianlibrary/TuzkaOCR/releases) before installing.

### Verify

```console
$ tuzkaocr page.jpg --format txt --out page.txt
Done in 2.4s — 37 lines → page.txt
```

## Running without installing

From the repository root:

```bash
pip install -r requirements.txt
python cli.py page.jpg --out result.alto.xml
```

Only this mode reads `tuzkaocr.env` — see
[Configuration](configuration.md#where-settings-come-from).

## Upgrading

`pip install .` does nothing if the version number is unchanged, so force it:

```bash
git pull
pip install --force-reinstall --no-deps .
```

## Development install

`pip install -e .` makes code and model edits take effect without reinstalling.
