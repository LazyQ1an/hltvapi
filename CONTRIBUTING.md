# Contributing to HLTV API

## Development Setup

```bash
git clone <repo>
cd hltv-pro-scraper
pip install -r requirements.txt
pip install pytest mypy ruff
```

## Code Style

- **Type hints**: All functions must have full type annotations
- **Pydantic v2**: All data models must use `pydantic.BaseModel`
- **Async-first**: All HTTP and I/O operations must be async
- **Defensive parsing**: Every element parse must be wrapped in try/except

## Adding a New Endpoint

See README → "How to Add a New Endpoint" section.

## Testing

```bash
# Capture fresh HTML fixtures from HLTV
python tests/capture_fixtures.py

# Run all tests
pytest tests/ -v

# Parse success monitoring
# The library logs a WARNING when parse ratio drops below 85%
```

## When HLTV Changes Their HTML

1. Run `python tests/capture_fixtures.py` to get new HTML
2. Run `pytest tests/ -v` to see which selectors fail
3. Update selectors in the relevant `src/endpoints/*.py` file
4. Verify with `pytest tests/ -v`

## Pull Request Checklist

- [ ] All tests pass: `pytest tests/ -v`
- [ ] No type errors: `mypy src/` (if configured)
- [ ] New endpoints include Pydantic models + parser tests
- [ ] README updated if adding features
