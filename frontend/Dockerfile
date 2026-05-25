# v4.1: Frontend Docker — Multi-stage Next.js build
# Target: minimal runtime image
# ─────────────────────────────────────────────────────────────────

# ── Stage 1: Builder ────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci --omit=dev --ignore-scripts

COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ── Stage 2: Runtime ────────────────────────────────────────
FROM node:20-alpine AS runtime

LABEL org.opencontainers.image.title="HLTV Pro Dashboard v4.1"
LABEL org.opencontainers.image.description="Next.js dashboard for HLTV Pro API"
LABEL org.opencontainers.image.version="4.1.0"

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000

COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

EXPOSE 3000

CMD ["node", "server.js"]
