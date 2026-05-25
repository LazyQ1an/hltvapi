# HLTV API — Agent Guide

## Quick start

```powershell
pip install -r requirements.txt
playwright install chromium  # only if using stealth mode
cp config.example.yaml config.yaml   # optional, all defaults are sensible
python main.py serve                  # start API on :8000
python main.py <command>              # CLI: upcoming, results, match, team, player, ranking, etc.
```

## Commands

| Task | Command |
|---|---|
| Run all tests | `pytest tests/ -v` |
| Single test | `pytest tests/test_matches.py -v -k "team_names"` |
| Lint | `ruff check src/ --ignore=E501` |
| Typecheck | `mypy src/ --ignore-missing-imports --check-untyped-defs` |
| Full pre-PR check | `ruff check src/ --ignore=E501` → `mypy src/ --ignore-missing-imports` → `pytest tests/ -v` |
| Capture fixtures | `python tests/capture_fixtures.py` (needed before first test run — no fixtures ship with repo) |
| Frontend dev | `cd frontend && npm run dev` |
| Frontend check | `cd frontend && npm run lint && npm run typecheck && npm run build` |
| Docker | `docker compose up -d` |

## Architecture

- **Entry point:** `main.py` dispatches to CLI (default) or FastAPI (`python main.py serve`). Routes are defined directly on `app` in `api.py` (flat, no nested routers).
- **Library under `src/`** with endpoint classes (e.g. `MatchesEndpoint`), Pydantic v2 models, and utilities.
- **Three-transport HTTP client** (`src/client.py`): `curl_cffi` (primary) → `httpx` (fallback) → `Playwright` (stealth escalation). Auto-escalates on block detection.
- **SessionPool** (`src/transport/`): 10-15 独立 session 轮换，每个有独立的 TLS fingerprint / UA / cookie jar / 健康度评分。
- **FetchPipeline** (`src/core/pipeline.py`): 统一请求执行管道（去重 → 限速 → transport 选择 → block 检测 → 归档）。
- **AdaptiveRateLimiter** (`src/antibot/`): 滑动时间窗口 + block_rate 动态调速 + 慢恢复。
- **BlockDetector** (`src/antibot/`): 5 级检测（状态码 → 关键词 → 响应体大小 → DOM 指纹 → 响应时间模式）。
- **HumanRequestPattern** (`src/antibot/`): burst（3-8 请求间隔 1-3s）+ rest（30-90s 停顿）模拟真人。
- **HTMLArchive** (`src/storage/`): append-only raw HTML 存储 + gzip + SQLite 索引，支持 replay。
- **LiveMatchTracker** (`src/core/live_tracker.py`): 比赛实时 polling，adaptive interval。
- **SemanticParser** (`src/parser/semantic.py`): 多层 CSS selector fallback + 命中率统计。
- **Three-tier cache** (`src/utils/cache.py`): L1 mem → L2 TTLCache → L3 diskcache/Redis. Write-through, promote on read hit.
- **All imports in `api.py` and `cli.py` are lazy** — done inside functions/methods, not at top level.
- **All endpoints do lazy imports** from their respective endpoint modules.

## Testing

- **HTML snapshot-based** — no live HTTP. Fixtures go in `tests/fixtures/` but directory is empty. Run `python tests/capture_fixtures.py` first.
- `conftest.py` provides fixture-loading helpers. Tests are parser-focused with threshold-based assertions (assert >=80% entries have expected fields).

## Conventions & quirks

- **Config loading** searches: `config.yaml` > `config.yml` > `config.example.yaml` (example IS valid config).
- **Env overrides** use `HLTV_` prefix with `__` for nesting (e.g. `HLTV_CLIENT__MODE=stealth`).
- **Parser adapter:** `src/parser.py` wraps selectolax nodes with BS4-compatible `.get()` / `.get_text()`. Endpoint code uses a single API regardless of parser backend.
- **`__init__.py`** files are non-empty — contain docs, exports, and `__all__`.
- **Scratch files** excluded by `.gitignore`: `_debug_*.py`, `_test_*.py`, `_analyze_*.py`, `_deep_*.py`, `_check_*.py`.
- **Frontend** is a separate Next.js 15 app under `frontend/`. Not needed for backend work.
- **No `.git` directory** — repo is not initialized despite having `.gitignore` and `.github/`.
- **CI runs in order:** ruff → mypy → pytest+coverage → bandit+safety → frontend lint+typecheck+build.
