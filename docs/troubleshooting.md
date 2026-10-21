# Troubleshooting

## Installation

??? failure "`pip install` fails on onnxruntime"
    Almost always an unsupported platform or interpreter. Confirm `python3 --version` is
    3.10 or newer, and that you are not on an **Intel Mac** — `onnxruntime` 1.18+ ships no
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
