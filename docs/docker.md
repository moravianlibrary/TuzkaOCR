# Docker

The CPU image is published for every release as `ghcr.io/moravianlibrary/tuzkaocr`, for
amd64 and arm64. A GPU image (`Dockerfile.gpu`) can be built locally. CPU is the supported
deployment.

## Published image

```bash
docker run -d -p 8000:8000 ghcr.io/moravianlibrary/tuzkaocr:1.9.0
curl http://localhost:8000/healthz
```

```json
{"status": "ok"}
```

Tags: an exact version (`1.9.0`), the latest patch of a minor version (`1.9`), and
`latest`. Pin an exact version in production.

### Setting an API key

Authentication is off by default. To turn it on, pass a key to the container:

```bash
KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
echo "$KEY"

docker run -d -p 8000:8000 \
  -e TUZKAOCR_API_KEY="$KEY" \
  ghcr.io/moravianlibrary/tuzkaocr:1.9.0

curl -H "X-API-Key: $KEY" http://localhost:8000/api/v1/models
```

Every request except `/healthz` must then send the key in the `X-API-Key` header. For one
key per caller, see [HTTP API](api.md#authentication).

## CPU service with Compose

From a clone of the repository, Compose adds the results directory, the spool volume,
`tuzkaocr.env` and the health check:

```bash
docker compose pull cpu
docker compose up -d cpu
```

`TUZKAOCR_VERSION=1.9.0` selects the image version (default `latest`), and
`TUZKAOCR_CPU_PORT` the host port (default 8000). To build the image from your checkout
instead, use `docker compose up --build -d cpu`.


## GPU service

```bash
docker compose --profile gpu up --build -d gpu
```

Port 8001 by default (`TUZKAOCR_GPU_PORT`). Requires the NVIDIA Container Toolkit.

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

Keep `./results` on persistent storage. Each service has its own spool volume; do not share
one between services.

### File ownership

Compose runs the container as `1000:1000`, so `./results` must be writable by that UID. If
your host account differs:

```bash
TUZKAOCR_RUN_UID=$(id -u) TUZKAOCR_RUN_GID=$(id -g) docker compose up -d cpu
```

## Running the CLI in a container

For a one-off batch without installing anything on the host:

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

Results land in `./results` on the host.

## Operational notes

- Health checks hit `/healthz`; shutdown waits up to 120 s for in-flight pages.
- Terminate TLS at a reverse proxy; the app speaks plain HTTP.
- Enable an API key for any non-local deployment (see
  [Setting an API key](#setting-an-api-key)). With Compose, set `TUZKAOCR_API_KEY` in
  `tuzkaocr.env`, or for per-caller keys mount the file and set `TUZKAOCR_API_KEYS_FILE`:

    ```yaml
    volumes:
      - ./api_keys.yaml:/app/api_keys.yaml:ro
    ```

- For memory sizing see [Configuration](configuration.md#memory).
