
# v4.0: Docker — Multi-stage build for HLTV Pro Scraper
# Target: 2-core, 2GB RAM servers
# ─────────────────────────────────────────────────────────────────

# ── Stage 1: Builder ────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libcurl4-openssl-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# ── Stage 2: Runtime ────────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="HLTV API v4.1"
LABEL org.opencontainers.image.description="Professional CS2 data API for HLTV.org"
LABEL org.opencontainers.image.version="4.1.0"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates libcurl4 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /root/.local /home/hltv/.local
ENV PATH=/home/hltv/.local/bin:$PATH

COPY main.py api.py cli.py ./
COPY src/ ./src/
COPY config/ ./config/

RUN mkdir -p data logs backups .cache/hltv

ENV HLTV_CLIENT__MODE=light \
    HLTV_CLIENT__MAX_CONCURRENCY=2 \
    HLTV_RATE_LIMIT__MIN_DELAY=2.0 \
    HLTV_RATE_LIMIT__MAX_DELAY=4.0 \
    HLTV_RATE_LIMIT__REQUESTS_PER_HOUR=300 \
    HLTV_CACHE__BACKEND=diskcache \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

RUN useradd -m -s /bin/bash hltv && chown -R hltv:hltv /app /home/hltv/.local
USER hltv

ENTRYPOINT ["python", "main.py"]
CMD ["serve"]
