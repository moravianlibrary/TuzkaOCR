# Docker

Two images are provided: a CPU image (`Dockerfile`) and a GPU image (`Dockerfile.gpu`).
Both carry the same code, so either can serve the HTTP API or run the CLI.

!!! tip "CPU is the recommended deployment"
    The GPU image is provided for completeness but is not yet performance-tuned — its
    pre- and post-processing layout differs from the CPU path. Use CPU unless you have a
    specific reason not to.

## CPU service

```bash
docker compose up --build -d cpu
curl http://localhost:8000/healthz
```

```json
{"status": "ok"}
```

The container listens on 8000. To publish a different host port:

```bash
TUZKAOCR_CPU_PORT=18080 docker compose up --build -d cpu
```

Logs show the auth mode, model loading, and readiness:

```bash
docker compose logs -f cpu
```

## GPU service

```bash
docker compose --profile gpu up --build -d gpu
```

Published on host port 8001 by default (`TUZKAOCR_GPU_PORT`), with
`TUZKAOCR_DEVICE=cuda` set for the service. Requires the NVIDIA Container Toolkit; the
Compose file reserves one NVIDIA device.

## Configuration

Both services read `tuzkaocr.env` from the repository root via `env_file`, then apply
service-specific overrides. Edit `tuzkaocr.env` and restart to change settings:

```bash
docker compose up -d --force-recreate cpu
```

The Compose file pins `TUZKAOCR_RESULTS_DIR=/app/results` and
`TUZKAOCR_SPOOL_DIR=/app/spool` for both services, so setting those two in `tuzkaocr.env`
has no effect. Everything else in [Configuration](configuration.md) applies.

## Storage

| Path in container | Backed by | Holds |
|---|---|---|
| `/app/results` | bind mount `./results` | Finished OCR output, swept by age |
| `/app/spool` | named volume (`cpu_spool` / `gpu_spool`) | Uploads in flight |

Results are bind-mounted so they are visible on the host; keep that directory on
persistent storage.

The spool is a **named volume per service**, which matters for two reasons: an explicitly
configured spool directory is treated as private to one service instance and is cleared of
leftovers at startup, so sharing one between services would let each delete the other's
uploads. It must also be real disk — a RAM-backed `tmpfs` would make large uploads count
against the container's memory limit.

### File ownership

The image creates an unprivileged `app` user (UID 10001), but Compose overrides the runtime
user to `1000:1000`:

```yaml
user: "${TUZKAOCR_RUN_UID:-1000}:${TUZKAOCR_RUN_GID:-1000}"
```

So `./results` on the host must be writable by that UID. If your host account is not 1000,
set it explicitly:

```bash
TUZKAOCR_RUN_UID=$(id -u) TUZKAOCR_RUN_GID=$(id -g) docker compose up -d cpu
```

Permission-denied errors when writing results are almost always this.

## Running the CLI in a container

Useful for a one-off batch without installing anything on the host. Mount the input
directory read-only:

```bash
docker compose run --rm --no-deps \
  -v "$PWD/input_pages:/app/input:ro" \
  cpu python cli.py /app/input \
  --batch \
  --format txt \
  --domain kramarky \
  --out-dir /app/results \
  --workers 2
```

`--no-deps` keeps the API service from starting alongside it, and `--rm` discards the
container afterwards. Results land in `./results` on the host.

## Operational notes

- **Health checks.** Both services define one against `/healthz` — 30 s interval, 60 s
  start period to allow for model loading. `/healthz` is never authenticated.
- **Graceful shutdown.** `stop_grace_period: 120s` lets in-flight pages finish; the server
  drains queued and running jobs on shutdown and logs how many.
- **Restart policy.** `restart: unless-stopped`, with `no-new-privileges:true` set.
- **Sizing.** Peak memory is roughly `0.1 GiB + PAGE_WORKERS × 1.3 GiB`. For tight limits,
  prefer one page worker per container and scale out by container count — see
  [memory](configuration.md#memory).
- **TLS.** Terminate TLS at a reverse proxy or ingress in front of the service; the app
  speaks plain HTTP.
- **Authentication.** Enable an API key for any deployment that is not strictly local. To
  use per-caller keys, mount the file and point the variable at it:

    ```yaml
    volumes:
      - ./api_keys.yaml:/app/api_keys.yaml:ro
    ```

    ```bash
    TUZKAOCR_API_KEYS_FILE=/app/api_keys.yaml
    ```
