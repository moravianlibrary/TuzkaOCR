FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tuzkaocr/ tuzkaocr/
COPY api/      api/
COPY cli.py    cli.py
COPY tuzkaocr.env tuzkaocr.env
COPY LICENSE NOTICE ./

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /app/results /app/input /app/spool /app/domains \
    && chown -R app:app /app \
    && chown 1000:1000 /app/domains \
    && chmod 0777 /app/spool

VOLUME ["/app/results", "/app/spool"]

EXPOSE 8000

ENV TUZKAOCR_RESULTS_DIR=/app/results \
    TUZKAOCR_SPOOL_DIR=/app/spool \
    TUZKAOCR_DOMAINS_DIR=/app/domains \
    TUZKAOCR_PACK_CACHE=/tmp/tuzkaocr-packs

USER app

CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
