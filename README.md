# HLTV API

> Async-first, anti-bot CS2 data API for HLTV.org — matches, teams, players, events, demos, news, search

Fetch Counter-Strike 2 match data, team information, player statistics, event details, news, and more — programmatically and reliably.

## ⚠️ Legal Disclaimer

**This project is for educational and research purposes only.** HLTV.org is a registered trademark. This scraper is not affiliated with, endorsed by, or sponsored by HLTV.org.

Before using this tool:

- Review [HLTV.org's Terms of Service](https://www.hltv.org/page/terms)
- Review [HLTV.org's robots.txt](https://www.hltv.org/robots.txt)
- Respect rate limits — aggressive scraping may get your IP banned
- Do not use scraped data for commercial purposes without permission
- The authors assume no liability for misuse

**Use at your own risk.**

## Features

- **Async-first**: Powered by `asyncio` + `httpx` + `curl_cffi` for maximum throughput
- **Anti-bot**: User-Agent rotation, TLS/JA3 fingerprint impersonation, Referer rotation
- **Stealth mode**: Automatic Playwright fallback when Cloudflare challenges are detected
- **Smart caching**: Pluggable backends — `diskcache` (default) or `redis`
- **Rate limiting**: Configurable delays with jitter and exponential backoff retry
- **Type-safe**: 100% Pydantic v2 models with full type hints
- **Dual interface**: Typer CLI + FastAPI REST API
- **Comprehensive**: Matches, results, teams, players, events, news, search, stats

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Install Playwright browser (for stealth mode)
playwright install chromium

# Copy and customize config
cp config.example.yaml config.yaml
```

### CLI

```bash
# Upcoming matches
python main.py upcoming

# Match results with pagination
python main.py results --page 2

# Match detail
python main.py match 2367256

# Team ranking
python main.py ranking

# Team detail & roster
python main.py team 6667
python main.py roster 6667

# Player detail
python main.py player 7993

# Top players
python main.py top-players --period last6months

# Events
python main.py events
python main.py event 7441

# News
python main.py news --limit 10

# Search
python main.py search "s1mple"
```

### API Server

```bash
python main.py serve
# → http://localhost:8000
# → http://localhost:8000/docs (Swagger UI)

# Or directly with uvicorn:
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

## Architecture

```
├── src/
│   ├── __init__.py       # Package init, version, exports
│   ├── config.py         # Pydantic-settings + YAML config
│   ├── client.py         # Async HTTP client (httpx + curl_cffi + Playwright)
│   ├── parser.py         # HTML parsing utilities
│   ├── models/           # Pydantic v2 data models
│   ├── endpoints/        # Scraper endpoint implementations (8 modules)
│   ├── utils/            # cache, logger, parsestats, retry
│   ├── warehouse/        # SQLite data warehouse (stdlib, no deps)
│   ├── scheduler/        # APScheduler daily jobs
│   ├── monitor/          # Health checks, WebSocket, webhook alerts
│   ├── plugins/          # Plugin system
│   └── db/               # PostgreSQL persistence (optional, SQLModel)
├── tests/                # pytest + HTML snapshot fixtures
├── dashboard.py          # Streamlit dashboard
├── cli.py                # Typer CLI (21 commands)
├── api.py                # FastAPI (26 routes + WS + metrics)
├── main.py               # Unified entry point
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── pyproject.toml         # ruff + mypy + pytest config
├── config.example.yaml
├── config/
│   └── low-resource.yaml # Low-resource deployment profile
├── scripts/
│   └── install.sh        # One-click deploy
├── .github/workflows/    # CI/CD pipelines
├── README.md
└── CONTRIBUTING.md
```

## Configuration

All settings are configured via `config.yaml` or environment variables (prefixed with `HLTV_`).

### Full Config Reference

```yaml
# Request mode
client:
  mode: "light"               # light | stealth
  timeout: 30                 # Request timeout (seconds)
  max_retries: 3
  curl_impersonate: true      # TLS fingerprint impersonation
  proxy: ~                    # Optional proxy URL
                                # e.g. "http://user:pass@host:port"
                                # Also reads HTTPS_PROXY env var

# Rate limiting — domain-level with hard caps
rate_limit:
  enabled: true
  min_delay: 1.5              # Gaussian center (seconds)
  max_delay: 3.0
  jitter: true
  requests_per_hour: 1000     # Hard cap (resets hourly)
  requests_per_day: 5000      # Hard cap (resets daily)

# Caching
cache:
  backend: "diskcache"        # diskcache | redis | none
  ttl: 300                    # Default TTL (seconds)
  diskcache_dir: ".cache/hltv"

# Logging
logging:
  level: "INFO"               # DEBUG | INFO | WARNING | ERROR
  format: "plain"             # plain | json
```

### Proxy Configuration

```bash
# Via config.yaml
client:
  proxy: "http://user:pass@1.2.3.4:8080"

# Via environment variable
export HTTPS_PROXY="socks5://127.0.0.1:1080"
```

### Environment Variables

```bash
# Override any config setting via env (nested keys with __)
export HLTV_CLIENT__MODE=stealth
export HLTV_RATE_LIMIT__MIN_DELAY=2.0
export HLTV_CACHE__BACKEND=redis
export HLTV_CACHE__REDIS_URL=redis://localhost:6379/0
```

## Troubleshooting

### Cloudflare 403 / Blocked

```
src.exceptions.BlockedError: Cloudflare challenge detected: https://www.hltv.org/...
```

1. **curl_cffi not installed** → `pip install curl-cffi` (primary TLS fingerprint layer)
2. **Outdated impersonation** → Update `impersonate="chrome124"` to latest Chrome version
3. **Too many requests** → Increase `min_delay` and `max_delay` in config
4. **Playwright not available** → `pip install playwright && playwright install chromium`
5. **Path is banned** → 3 consecutive failures on same path triggers temp ban (5 min auto-clear)

### Rate Limited (429)

```
src.exceptions.RateLimitError: Rate limited: https://www.hltv.org/...
```

The rate limiter auto-backs off exponentially. If you hit this:
- Reduce concurrency or increase delays
- Check `requests_per_hour` / `requests_per_day` caps
- Enable cache to reduce redundant requests

### All Methods Failed

```
src.exceptions.HTTPError: All request methods failed for https://www.hltv.org/...
```

The client tried curl_cffi, httpx, and Playwright (if available) — all failed.

**Causes:**
- Network connectivity issues
- Proxy misconfiguration  
- All transports are blocked by Cloudflare
- DNS resolution failure

**Fix:** Check network, try without proxy, or use `stealth` mode with Playwright installed.

### Parser Returns No Data

If an endpoint returns 0 items or empty fields:

1. HLTV has likely changed their HTML structure
2. Run `python tests/capture_fixtures.py` to get fresh HTML snapshots
3. Check the selectors in the relevant endpoint file
4. Run tests: `pytest tests/ -v` to see which selectors fail
5. Update selectors to match new HTML

## How to Add a New Endpoint

1. **Define models** in `src/models/` — create Pydantic v2 classes for your data
2. **Create endpoint** in `src/endpoints/` — follow this pattern:

```python
from src.client import HLTVClient
from src.parser import select_one, select_all, safe_text

class NewEndpoint:
    def __init__(self, client: HLTVClient) -> None:
        self._client = client

    async def get_data(self) -> list[YourModel]:
        soup = await self._client.get_soup("https://www.hltv.org/page")
        results = []
        for element in select_all(soup, ".selector"):
            try:
                results.append(YourModel(
                    field=safe_text(select_one(element, ".field-selector")),
                ))
            except Exception as e:
                logger.debug("Parse error: %s", e)
                continue
        return results
```

3. **Register in CLI** — add a `@app.command()` in `cli.py`
4. **Register in API** — add a route in `api.py`
5. **Add tests** — create `tests/test_new.py` with HTML snapshots
6. **Export** — add to `src/endpoints/__init__.py`

## Testing

```bash
# Capture live HTML fixtures
python tests/capture_fixtures.py

# Run all tests
pytest tests/ -v

# Run specific test
pytest tests/test_matches.py -v -k "team_names"

# Parse success monitoring (built-in)
# Each endpoint tracks parse success ratio and warns if below 85%
```

## Cache Control

```bash
# CLI
python main.py clear-cache

# API
curl -X POST http://localhost:8000/cache/clear
```

Cache TTL can be set per-request or globally in config.

## License

MIT
