"""
FastAPI-based REST API for the HLTV scraper.

Provides HTTP endpoints to all major scraper functionality.
Run with: uvicorn api:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import time as tmod
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from src.security.headers import SecurityHeadersMiddleware
from src.security.api_keys import verify_api_key, is_auth_enabled
from src.monitor.resources import get_resource_usage

# OpenTelemetry (optional observability)
_HAS_OTEL = False
try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    _HAS_OTEL = True
except ImportError:
    pass

# Prometheus metrics (optional)
_HAS_PROMETHEUS = False
try:
    from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
    _HAS_PROMETHEUS = True
except ImportError:
    pass

from src.client import HLTVClient
from src.config import HLTVConfig
from src.utils.logger import get_logger, setup_logger

# ── Application state ───────────────────────────────────────────────

config: HLTVConfig | None = None
client: HLTVClient | None = None
_scheduler: Any | None = None
logger = get_logger("api")

# ── Prometheus metrics (optional) ────────────────────────────────────

if _HAS_PROMETHEUS:
    REQUEST_COUNT = Counter("hltv_requests_total", "Total HTTP requests", ["endpoint", "status"])
    REQUEST_LATENCY = Histogram("hltv_request_duration_seconds", "Request latency", ["endpoint"])
    PARSE_RATIO = Gauge("hltv_parse_ratio", "Parse success ratio", ["parser"])
    RATE_LIMITER_USAGE = Gauge("hltv_rate_limiter_usage", "Rate limiter usage", ["type"])
    DATA_COUNT = Gauge("hltv_data_count", "Data warehouse counts", ["table"])


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    """Application lifespan: initialize and clean up."""
    global client, config, _scheduler
    config = HLTVConfig.load()
    setup_logger(config.logging)
    client = HLTVClient(config)

    # Start scheduler if enabled
    try:
        from src.scheduler import start_scheduler
        from src.warehouse import Warehouse
        db = Warehouse("hltv_data.sqlite")
        db.create_tables()
        _scheduler = start_scheduler(client, db)
        logger.info("Scheduler started for daily snapshots")
    except Exception as e:
        logger.info("Scheduler not started: %s", e)

    yield

    if _scheduler:
        try:
            from src.scheduler import stop_scheduler
            stop_scheduler(_scheduler)
        except Exception:
            pass
    if client:
        await client.close()


app = FastAPI(
    title="HLTV Pro API",
    description="Professional CS2 data API for HLTV.org — v4.0",
    version="4.0.0",
    lifespan=lifespan,
)

# v4.0: Security middleware
app.add_middleware(SecurityHeadersMiddleware)

# CORS for frontend — restrict in production
import os
_cors_origins = os.environ.get(
    "HLTV_CORS_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000"
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins if o.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)

# Optional global API key protection
if is_auth_enabled():
    from fastapi import Depends
    app.router.dependencies.append(Depends(verify_api_key))


def _get_client() -> HLTVClient:
    """Get the global HLTV client."""
    if client is None:
        raise HTTPException(status_code=500, detail="Client not initialized")
    return client


# ── Prometheus middleware (optional) ─────────────────────────────────


if _HAS_PROMETHEUS:
    @app.middleware("http")
    async def prometheus_middleware(request: Any, call_next: Any) -> Any:
        """Record request count and latency for Prometheus."""
        start = tmod.time()
        response = await call_next(request)
        duration = tmod.time() - start
        endpoint = request.url.path
        status = str(response.status_code) if response.status_code else "200"
        REQUEST_COUNT.labels(endpoint=endpoint, status=status).inc()
        REQUEST_LATENCY.labels(endpoint=endpoint).observe(duration)
        return response


def _serialize(data: Any) -> Any:
    """Serialize Pydantic models to JSON-compatible dicts."""
    if hasattr(data, "model_dump"):
        return data.model_dump(mode="json")
    if isinstance(data, list):
        return [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            for item in data
        ]
    if isinstance(data, dict):
        return {
            k: v.model_dump(mode="json") if hasattr(v, "model_dump") else v
            for k, v in data.items()
        }
    return data


# ── Health & Metrics ────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    cfg = _get_client().config
    return {
        "status": "ok",
        "mode": cfg.client.mode,
        "cache": cfg.cache.backend,
    }


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """WebSocket endpoint for real-time monitoring alerts.

    Connect: ws://localhost:8000/ws
    Receives alert broadcasts from the monitoring system.
    """
    from src.monitor.ws import websocket_endpoint as ws_handler
    await ws_handler(ws)


if _HAS_PROMETHEUS:
    @app.get("/metrics")
    async def metrics() -> Any:
        """Prometheus metrics endpoint."""
        from fastapi.responses import Response

        cl = _get_client()
        limiter = cl._rate_limiter.get_stats()
        RATE_LIMITER_USAGE.labels(type="hourly").set(limiter.get("hourly_used", 0))
        RATE_LIMITER_USAGE.labels(type="daily").set(limiter.get("daily_used", 0))

        from src.utils.parsestats import report_all
        for name, stats in report_all().items():
            PARSE_RATIO.labels(parser=name).set(stats.get("ratio", 1.0))

        try:
            from src.warehouse import Warehouse
            db = Warehouse("hltv_data.sqlite")
            for table, count in db.get_stats().items():
                DATA_COUNT.labels(table=table).set(count)
        except Exception:
            pass

        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/monitoring")
async def monitoring() -> dict[str, Any]:
    """Monitoring metrics endpoint."""
    import time as tmod
    cl = _get_client()
    cfg = cl.config

    # Rate limiter stats
    limiter_stats = cl._rate_limiter.get_stats()

    # Parse stats
    from src.utils.parsestats import report_all
    parse_stats = report_all()

    # Determine overall health
    low_ratio_parsers = [
        name for name, s in parse_stats.items()
        if s["total"] > 0 and s["ratio"] < 0.85
    ]
    alerts: list[str] = []
    if low_ratio_parsers:
        alerts.append("Low parse ratio: {}".format(", ".join(low_ratio_parsers)))
    if limiter_stats.get("hourly_used", 0) > limiter_stats.get("hourly_limit", 0) * 0.9:
        alerts.append("Hourly rate limit approaching ({}%)".format(
            round(limiter_stats["hourly_used"] / max(limiter_stats["hourly_limit"], 1) * 100)
        ))

    return {
        "status": "degraded" if alerts else "healthy",
        "alerts": alerts,
        "uptime_seconds": None,
        "rate_limiter": limiter_stats,
        "parse_stats": parse_stats,
        "config": {
            "mode": cfg.client.mode,
            "min_delay": cfg.rate_limit.min_delay,
            "max_delay": cfg.rate_limit.max_delay,
            "hourly_limit": cfg.rate_limit.requests_per_hour,
            "daily_limit": cfg.rate_limit.requests_per_day,
            "cache_backend": cfg.cache.backend,
            "curl_impersonate": cfg.client.curl_impersonate,
        },
    }


# ── Matches ─────────────────────────────────────────────────────────


@app.get("/matches/upcoming")
async def get_upcoming() -> list[Any]:
    """Get upcoming matches."""
    from src.endpoints.matches import MatchesEndpoint
    matches = await MatchesEndpoint(_get_client()).get_upcoming()
    return _serialize(matches)


@app.get("/matches/results")
async def get_results(
    page: int = Query(1, ge=1, description="Page number"),
    start_date: str | None = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: str | None = Query(None, description="End date (YYYY-MM-DD)"),
) -> list[Any]:
    """Get historical match results."""
    from src.endpoints.results import ResultsEndpoint
    matches = await ResultsEndpoint(_get_client()).get_results(
        page=page,
        start_date=start_date,
        end_date=end_date,
    )
    return _serialize(matches)


@app.get("/matches/{match_id}")
async def get_match(match_id: int) -> Any:
    """Get detailed match information by ID."""
    from src.endpoints.matches import MatchesEndpoint
    detail = await MatchesEndpoint(_get_client()).get_detail(match_id)
    return _serialize(detail)


# ── Teams ───────────────────────────────────────────────────────────


@app.get("/teams/ranking")
async def get_ranking() -> Any:
    """Get world team ranking."""
    from src.endpoints.teams import TeamsEndpoint
    ranking = await TeamsEndpoint(_get_client()).get_ranking()
    return _serialize(ranking)


@app.get("/teams/{team_id}")
async def get_team(team_id: int) -> Any:
    """Get team details by ID."""
    from src.endpoints.teams import TeamsEndpoint
    detail = await TeamsEndpoint(_get_client()).get_detail(team_id)
    return _serialize(detail)


@app.get("/teams/{team_id}/roster")
async def get_team_roster(team_id: int) -> list[Any]:
    """Get team roster by ID."""
    from src.endpoints.teams import TeamsEndpoint
    roster = await TeamsEndpoint(_get_client()).get_roster(team_id)
    return _serialize(roster)


@app.get("/teams/{team_id}/matches")
async def get_team_matches(team_id: int) -> list[Any]:
    """Get recent matches for a team."""
    from src.endpoints.teams import TeamsEndpoint
    matches = await TeamsEndpoint(_get_client()).get_recent_matches(team_id)
    return _serialize(matches)


# ── Players ─────────────────────────────────────────────────────────


@app.get("/players/{player_id}")
async def get_player(player_id: int) -> Any:
    """Get player details by ID."""
    from src.endpoints.players import PlayersEndpoint
    detail = await PlayersEndpoint(_get_client()).get_detail(player_id)
    return _serialize(detail)


@app.get("/players/top")
async def get_top_players(
    period: str = Query("last3months", description="Time period: last3months, last6months, last12months, alltime, currentyear, bigevents"),
) -> Any:
    """Get top player rankings."""
    from src.endpoints.players import PlayersEndpoint
    response = await PlayersEndpoint(_get_client()).get_top_players(period)
    return _serialize(response)


@app.get("/players/{player_id}/maps")
async def get_player_map_stats(player_id: int) -> list[Any]:
    """Get per-map statistics for a player."""
    from src.endpoints.players import PlayersEndpoint
    stats = await PlayersEndpoint(_get_client()).get_map_stats(player_id)
    return _serialize(stats)


# ── Events ──────────────────────────────────────────────────────────


@app.get("/events")
async def get_events(
    ongoing: bool = Query(False, description="Only ongoing events"),
) -> list[Any]:
    """Get event listings."""
    from src.endpoints.events import EventsEndpoint
    ep = EventsEndpoint(_get_client())
    data = await (ep.get_ongoing() if ongoing else ep.get_events())
    return _serialize(data)


@app.get("/events/{event_id}")
async def get_event(event_id: int) -> Any:
    """Get event details by ID."""
    from src.endpoints.events import EventsEndpoint
    detail = await EventsEndpoint(_get_client()).get_detail(event_id)
    return _serialize(detail)


# ── News ────────────────────────────────────────────────────────────


@app.get("/news")
async def get_news(
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(30, ge=1, le=100, description="Items per page"),
) -> Any:
    """Get news articles."""
    from src.endpoints.news import NewsEndpoint
    articles = await NewsEndpoint(_get_client()).get_news(offset=offset, limit=limit)
    return _serialize(articles)


@app.get("/news/{article_id}")
async def get_news_detail(article_id: int) -> Any:
    """Get full article content by ID."""
    from src.endpoints.news import NewsEndpoint
    detail = await NewsEndpoint(_get_client()).get_detail(article_id)
    return _serialize(detail)


# ── Search ──────────────────────────────────────────────────────────


@app.get("/search")
async def search(
    q: str = Query(..., min_length=1, description="Search query"),
) -> dict[str, list[Any]]:
    """Search HLTV for players, teams, matches, events, news."""
    from src.endpoints.search import SearchEndpoint
    results = await SearchEndpoint(_get_client()).search(q)
    return _serialize(results)


# ── Stats ───────────────────────────────────────────────────────────


@app.get("/stats/team/{team_id}")
async def get_team_stats(team_id: int) -> dict[str, Any]:
    """Get statistics for a specific team."""
    from src.endpoints.stats import StatsEndpoint
    stats = await StatsEndpoint(_get_client()).get_team_stats(team_id)
    return _serialize(stats)


# ── Demos ────────────────────────────────────────────────────────────


@app.get("/matches/{match_id}/demos")
async def get_demos(match_id: int) -> list[Any]:
    """List available demo downloads for a match."""
    from src.endpoints.demos import DemosEndpoint
    demos = await DemosEndpoint(_get_client()).get_demos(match_id)
    return _serialize(demos)


# ── Cache ───────────────────────────────────────────────────────────


@app.post("/cache/clear")
async def clear_cache() -> dict[str, str]:
    """Clear the response cache."""
    _get_client().clear_cache()
    return {"status": "cache cleared"}


# ── v4.0: Resource Monitoring ────────────────────────────────────────


@app.get("/resources")
async def get_resources() -> dict:
    """Get current server resource usage (CPU, memory, disk, network)."""
    return get_resource_usage()


# ── v4.0: Export Center ──────────────────────────────────────────────


@app.get("/export/pdf")
async def export_pdf(
    data_type: str = Query("matches", pattern="^(matches|ranking|players)$"),
    page: int = Query(1, ge=1),
) -> Response:
    """Export data as styled PDF report."""
    from src.export.pdf import generate_pdf_report
    cl = _get_client()
    pdf_bytes = await generate_pdf_report(cl, data_type, page)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f"attachment; filename=hltv-{data_type}-report.pdf"
            ),
        },
    )


@app.get("/export/excel")
async def export_excel(
    data_type: str = Query("matches", pattern="^(matches|ranking|players)$"),
    page: int = Query(1, ge=1),
) -> Response:
    """Export data as styled Excel spreadsheet."""
    from src.export.excel import generate_excel_report
    cl = _get_client()
    xlsx_bytes = await generate_excel_report(cl, data_type, page)
    return Response(
        content=xlsx_bytes,
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": (
                f"attachment; filename=hltv-{data_type}-data.xlsx"
            ),
        },
    )


# ── v4.0: Data Comparison ────────────────────────────────────────────


@app.get("/comparison/{compare_type}")
async def compare(
    compare_type: str,
    ids: str = Query(..., description="Comma-separated IDs, e.g. 6667,4608"),
) -> dict:
    """Compare teams or players side by side (2-5 IDs)."""
    id_list = [int(i.strip()) for i in ids.split(",") if i.strip()]
    if len(id_list) < 2 or len(id_list) > 5:
        raise HTTPException(
            status_code=400,
            detail="Provide 2-5 comma-separated IDs",
        )
    cl = _get_client()

    if compare_type == "teams":
        from src.endpoints.teams import TeamsEndpoint
        ep = TeamsEndpoint(cl)
        results = {}
        for tid in id_list:
            try:
                results[str(tid)] = _serialize(
                    await ep.get_detail(tid),
                )
            except Exception as e:
                results[str(tid)] = {"error": str(e)}
        return {"type": "teams", "results": results}

    elif compare_type == "players":
        from src.endpoints.players import PlayersEndpoint
        ep = PlayersEndpoint(cl)
        results = {}
        for pid in id_list:
            try:
                results[str(pid)] = _serialize(
                    await ep.get_detail(pid),
                )
            except Exception as e:
                results[str(pid)] = {"error": str(e)}
        return {"type": "players", "results": results}

    raise HTTPException(
        status_code=400,
        detail="compare_type must be 'teams' or 'players'",
    )
