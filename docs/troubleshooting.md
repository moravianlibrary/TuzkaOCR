# Troubleshooting

## Installation

??? failure "`pip install` fails on onnxruntime"
    Almost always an unsupported platform or interpreter. Confirm `python3 --version` is
    3.10 or newer, and that you are not on an **Intel Mac** — `onnxruntime` 1.18+ ships no
    x86-64 macOS wheels. Use the [Docker CPU image](docker.md) there.

??? failure "`tuzkaocr: command not found`"
    The virtual environment is not active. Re-run `source .venv/bin/activate`, or call the
    binary by path: `.venv/bin/tuzkaocr`. To see which install answers, use
    `which tuzkaocr` and `pip show tuzkaocr`.

??? failure "A new model or setting seems to be missing after upgrading"
    `pip install .` is a no-op when the version in `pyproject.toml` has not changed, so the
    old code and models can survive a `git pull`. Force it:

    ```bash
    pip install --force-reinstall --no-deps .
    pip show tuzkaocr | head -2
    ```

??? failure "`tuzkaocr.env` is ignored"
    Expected for an installed package: the file is looked up next to the package directory,
    which after installation is `site-packages/`. Use real environment variables, or a `.env`
    in the working directory. See
    [where settings come from](configuration.md#where-settings-come-from).

## Output quality

??? failure "Text is garbled, or lines are missing"
    In order:

    1. **Check the domain.** The wrong model pair costs more accuracy than every other
       setting combined. See [Models and domains](models.md).
    2. **Leave adaptive downsampling on** for dense multi-column pages — do not pass
       `--no-adaptive`.
    3. **Try `--height-scale 1.5`** if crops appear to clip ascenders or descenders.
    4. **Check the scan.** Below roughly 200 dpi, no setting recovers the page.

    For API jobs, `mean_conf` from the status endpoint is a good triage signal — low values
    flag pages worth re-scanning rather than re-running.

??? failure "Kramarky output is poor on a newspaper"
    The kramarky pair is for kramarky broadsheet prints specifically, not periodicals in
    general. Use the printed domain with adaptive downsampling enabled.

??? failure "Role tags are missing from the ALTO"
    Two expected causes before suspecting a bug: role classification is off by default
    (enable with `--role-classifier`, `role_classifier=true`, or
    `TUZKAOCR_ROLE_CLASSIFIER=true`), and `body` lines are deliberately never tagged. The
    classifier also stays silent when unsure. See
    [line roles](output-formats.md#line-roles).

## Running out of memory

??? failure "The process is killed during a batch"
    The layout detector holds a transient of about 1.3 GiB per page in flight, so peak memory
    is roughly `0.1 GiB + PAGE_WORKERS × 1.3 GiB`. Drop to one worker and release memory
    between pages:

    ```bash
    TUZKAOCR_CPU_MEM_ARENA=false tuzkaocr input/ --batch --workers 1
    ```

    One worker then fits in about 1.2 GiB, two in about 2 GiB. Scale out by adding
    instances rather than workers. Full detail in [memory](configuration.md#memory).

??? failure "Idle memory stays high after a batch finishes"
    By design: ONNX Runtime's CPU arena keeps its pool and does not return it to the OS.
    Set `TUZKAOCR_CPU_MEM_ARENA=false` to trade about 35% single-page latency for a roughly
    45% lower peak — batch throughput only drops about 6%.

## Service errors

??? failure "503 with a `Retry-After` header"
    Queued plus running jobs have reached `TUZKAOCR_MAX_QUEUE` (default 16). Honour the
    header and retry after the given delay; immediate retries are refused again. Raise
    throughput with `TUZKAOCR_PAGE_WORKERS`, not by raising the queue cap — a deeper queue
    only lengthens the wait.

??? failure "413 on upload"
    The request body exceeds `TUZKAOCR_MAX_UPLOAD_MB` (default 256). Raise it, or send a
    smaller derivative.

??? failure "422, or a job that fails with a decode error"
    The image could not be decoded, or it exceeds `TUZKAOCR_MAX_IMAGE_PIXELS` (default 300
    megapixels). Uploads are accepted before decoding, so this arrives as a **failed job**
    rather than a rejected request; the message is in the status response's `error` field.

??? failure "404 from `status` for a job that definitely existed"
    Either the job aged out past `TUZKAOCR_MAX_JOB_AGE_HOURS` (default 24), or the server
    restarted — job metadata is in memory. The **result** endpoint may still work, because it
    falls back to finding the file by job ID on disk. Keep job IDs client-side.

??? failure "Permission denied writing to `results/`"
    Compose runs the container as `1000:1000` by default, which may not match your host
    account:

    ```bash
    TUZKAOCR_RUN_UID=$(id -u) TUZKAOCR_RUN_GID=$(id -g) docker compose up -d cpu
    ```

??? failure "The server exits at startup with a configuration error"
    Working as intended — configuration is validated before models load, and the message
    names every problem at once. Common causes: a zero or negative worker count, a device
    other than `cpu`/`cuda`/`auto`, `TUZKAOCR_HEIGHT_SCALE` outside 0.1–10.0, a
    `TUZKAOCR_SPOOL_DIR` that does not exist, or an unresolvable model name. Note that
    booleans accept only `1`, `true`, and `yes` — `on` and `y` read as false.

??? failure "GPU is not being used"
    `TUZKAOCR_DEVICE=auto` falls back to CPU unless `onnxruntime` reports a CUDA execution
    provider, and the pinned `onnxruntime` wheel is CPU-only. Use the GPU image, which
    requires the NVIDIA Container Toolkit. CPU remains the recommended deployment — the GPU
    path is not yet performance-tuned.
