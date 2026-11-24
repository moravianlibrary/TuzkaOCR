# Troubleshooting

## Installation

??? failure "The one-line installer fails or is blocked"
    The script prints `TuzkaOCR install failed:` and the reason.

    - **Nothing happens, or security software reports the line** — the computer is managed
      and blocks installing software (Group Policy execution policy, AppLocker, endpoint
      protection). Ask IT to allow it, or install [without uv](beginners.md#without-uv).
    - **`could not reach GitHub`** — a proxy or firewall blocks `github.com`. The installer
      also needs `astral.sh` (uv), `pypi.org` and `files.pythonhosted.org` (libraries) and
      `github.com` / `objects.githubusercontent.com` (Python and TuzkaOCR).
    - **`Intel Macs are not supported`** — use the [Docker image](docker.md).
    - **`this Terminal runs under Rosetta`** — in Finder, select Terminal in Applications →
      Utilities, choose *Get Info*, untick *Open using Rosetta*, and run the line again.
    - **`tuzkaocr` is not found afterwards** — open a new terminal window; windows opened
      before the install do not see it.

??? failure "`tuzkaocr app` does not open the browser, or the page cannot be reached"
    - **No browser opens** — common on servers and some Linux desktops. Copy the
      `http://127.0.0.1:…/?k=…` line the terminal printed into a browser on the same
      computer.
    - **The page cannot be reached, or says *TuzkaOCR has stopped*** — the terminal running
      the app was closed. Start `tuzkaocr app` again; each start uses a new address and key,
      so old tabs say *This page belongs to an earlier TuzkaOCR window*.
    - **On another computer** — not supported: the app listens on `127.0.0.1` only. Use the
      [HTTP API](api.md) for remote use.

??? failure "`tuzkaocr app` says *macOS is blocking this folder* or *This folder cannot be opened*"
    - **macOS is blocking this folder** — macOS privacy protection. Desktop, Documents,
      Downloads and removable drives need permission for the terminal app that started
      TuzkaOCR (Terminal, iTerm, …). macOS asks only once; after a refusal, turn it on in
      **System Settings → Privacy & Security → Files & Folders →** the terminal app, or reset
      the answer so it asks again, for example
      `tccutil reset SystemPolicyDesktopFolder com.apple.Terminal` (iTerm:
      `com.googlecode.iterm2`). Quit the terminal and start the app again.
    - **This folder cannot be opened** — the account running the app has no read
      permission for the folder.

??? failure "`pip install` tries to build scipy or numpy, or asks for gfortran or a Fortran compiler"
    Your Python is too new. TuzkaOCR supports Python 3.11 to 3.14; on 3.15 no ready-made
    packages exist, so pip falls back to compiling them from source and fails. Do not
    install a Fortran compiler — it only moves the failure to the next package. Either
    [install with the one-line installer](install.md#install-with-uv), which fetches a
    supported Python itself, or
    [install Python 3.14](beginners.md#install-python), create the virtual environment with
    it, and install again.

??? failure "`pip install` fails on onnxruntime"
    Almost always an unsupported platform or interpreter. Confirm `python3 --version` is
    between 3.11 and 3.14, and that you are not on an **Intel Mac** — `onnxruntime` 1.18+ ships no
    x86-64 macOS wheels. Use the [Docker CPU image](docker.md) there.

??? failure "`tuzkaocr: command not found`"
    The virtual environment is not active. Re-run `source .venv/bin/activate`.

??? failure "A new model or setting seems to be missing after upgrading"
    Reinstall with `pip install --force-reinstall --no-deps .` — see
    [Upgrading](install.md#upgrading).

??? failure "`tuzkaocr.env` is ignored"
    Expected for an installed package. Use environment variables or a `.env` in the working
    directory — see [where settings come from](configuration.md#where-settings-come-from).

## Output quality

??? failure "Text is garbled, or lines are missing"
    In order:

    1. **Check the domain** — see [Models and domains](models.md).
    2. **Leave adaptive downsampling on** (do not pass `--no-adaptive`).
    3. **Try `--height-scale 1.5`** if crops clip ascenders or descenders.
    4. **Check the scan.** Below roughly 200 dpi, no setting recovers the page.

??? failure "A scan is sideways or upside down"
    Pass `--orientation auto` (`TUZKAOCR_ORIENTATION=auto`). If upside-down pages still slip
    through, also set `TUZKAOCR_ORIENTATION_RECHECK=on` — see
    [page orientation](configuration.md#page-orientation).

??? failure "Pale carbon copies or faint typewriter text are hard to read"
    Try `--contrast auto` (`TUZKAOCR_CONTRAST=auto`) — see
    [contrast normalisation](configuration.md#contrast-normalisation).

??? failure "Faint text is missing, or show-through is read as gibberish"
    [Show-through removal](configuration.md#show-through) is on for printed pages. To keep
    all faint text, pass `--no-showthrough` (`TUZKAOCR_SHOWTHROUGH=false`, API
    `showthrough=false`).

??? failure "Columns or articles are read in the wrong order"
    Try `TUZKAOCR_READING_ORDER=basic` (CLI `--reading-order basic`) — see
    [reading order](configuration.md#reading-order).

??? failure "A newspaper title is garbled or missing"
    Check that [large text](configuration.md#large-text) is not disabled. Ornate display
    faces may still be misread.

??? failure "Kramarky output is poor on a newspaper"
    `kramarky` is for kramarky broadsheets only. Use the default domain.

??? failure "Role tags are missing from the ALTO"
    Role classification is off by default, and `body` lines are never tagged. See
    [line roles](output-formats.md#line-roles).

## Running out of memory

??? failure "The process is killed during a batch"
    Each worker needs about 1.3 GiB. Drop to one worker and release memory between pages:

    ```bash
    TUZKAOCR_CPU_MEM_ARENA=false tuzkaocr input/ --batch --workers 1
    ```

    See [memory](configuration.md#memory).

??? failure "Idle memory stays high after a batch finishes"
    By design; set `TUZKAOCR_CPU_MEM_ARENA=false` — see [memory](configuration.md#memory).

## Service errors

??? failure "503 with a `Retry-After` header"
    The queue is full (`TUZKAOCR_MAX_QUEUE`). Retry after the given delay; raise throughput
    with `TUZKAOCR_PAGE_WORKERS`.

??? failure "413 on upload"
    The request body exceeds `TUZKAOCR_MAX_UPLOAD_MB` (default 256). Raise it, or send a
    smaller derivative.

??? failure "422, or a job that fails with a decode error"
    The image could not be decoded or exceeds `TUZKAOCR_MAX_IMAGE_PIXELS` (default 300
    megapixels). The message is in the status response's `error` field.

??? failure "404 from `status` for a job that definitely existed"
    The job aged out (`TUZKAOCR_MAX_JOB_AGE_HOURS`) or the server restarted. The **result**
    endpoint may still serve the file.

??? failure "Permission denied writing to `results/`"
    Compose runs the container as `1000:1000`:

    ```bash
    TUZKAOCR_RUN_UID=$(id -u) TUZKAOCR_RUN_GID=$(id -g) docker compose up -d cpu
    ```

??? failure "The server exits at startup with a configuration error"
    The message names every invalid setting. Note that booleans accept only `1`, `true` and
    `yes`.

??? failure "GPU is not being used"
    The pinned `onnxruntime` is CPU-only. Use the [GPU image](docker.md#gpu-service).

## Custom domain packs

??? failure "A pack is missing from `--list-domains`"
    Check that the `.tpack` or pack folder is directly inside `TUZKAOCR_DOMAINS_DIR`.
    Non-default packs with invalid manifests, checksums, or version requirements are skipped
    with a warning. Run `python cli.py --check-domains` for the full validation report.

??? failure "`sha256 mismatch for <file>`"
    The file differs from the checksum in `domain.json`. Re-copy the complete pack from its
    provider rather than editing one model file in place.

??? failure "`unknown setting key '<key>'` or an invalid setting value"
    Remove the unsupported setting or correct its value, then ask the pack provider to rebuild
    the archive. Pack settings use the same ranges as the corresponding `TUZKAOCR_*` setting.

??? failure "`requires_tuzkaocr` is unsupported or does not match this version"
    Use a pack built for the installed core version, or install a compatible TuzkaOCR release.

??? failure "`unsafe zip member` or a `.tpack` size-limit error"
    The archive contains a path outside its root, nested folders, or more than the allowed
    uncompressed size. Ask the provider for a corrected archive.

??? failure "`model ... expects N classes, vocab ... covers M`"
    The recognizer and vocabulary do not match. Pass the vocabulary shipped with that model;
    every custom recognizer needs its matching vocabulary.

??? failure "Unknown domain in the CLI or API"
    Run `python cli.py --list-domains` or query `/api/v1/models`; use a listed built-in or pack
    name. An explicit `print` selection bypasses a pack default.

## Still stuck?

Write to us, with the exact command or what you clicked, and the last lines the terminal
printed:

- Filip Bím — [filip.bim@mzk.cz](mailto:filip.bim@mzk.cz)
- Martina Dvořáková — [dvorakovam@mzk.cz](mailto:dvorakovam@mzk.cz)
