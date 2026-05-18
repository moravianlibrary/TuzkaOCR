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

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /app/results /app/input \
    && chown -R app:app /app

VOLUME ["/app/results"]

EXPOSE 8000

ENV TUZKAOCR_RESULTS_DIR=/app/results

USER app

CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
