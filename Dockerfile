
# v4.1: Docker — Multi-stage build for HLTV Pro Scraper
# Target: 2-core, 2GB RAM servers

FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libcurl4-openssl-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt
RUN pip install --user --no-cache-dir playwright

FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="HLTV API v4.1"
LABEL org.opencontainers.image.description="Professional CS2 data API for HLTV.org"
LABEL org.opencontainers.image.version="4.1.0"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates libcurl4 \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 \
    libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    fonts-liberation xdg-utils \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

RUN python3 -m playwright install chromium

RUN useradd -m -s /bin/bash hltv \
    && cp -r /root/.local /home/hltv/.local \
    && mkdir -p /home/hltv/.cache \
    && cp -r /root/.cache/ms-playwright /home/hltv/.cache/ms-playwright \
    && chown -R hltv:hltv /home/hltv/.local /home/hltv/.cache

COPY main.py api.py cli.py ./
COPY src/ ./src/
COPY config/ ./config/

RUN mkdir -p data logs backups .cache/hltv \
    && chown -R hltv:hltv /app

ENV HLTV_CLIENT__MODE=light \
    HLTV_CLIENT__MAX_CONCURRENCY=2 \
    HLTV_RATE_LIMIT__MIN_DELAY=2.0 \
    HLTV_RATE_LIMIT__MAX_DELAY=4.0 \
    HLTV_RATE_LIMIT__REQUESTS_PER_HOUR=300 \
    HLTV_CACHE__BACKEND=diskcache \
    HLTV_PLAYWRIGHT_HEADLESS=true \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

USER hltv

ENTRYPOINT ["python", "main.py"]
CMD ["serve"]
