"""
Typer-based CLI for the HLTV scraper.

Provides a command-line interface to all major scraper endpoints.
"""

from __future__ import annotations

import asyncio
import json
import sys
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import typer
from typing_extensions import Annotated

from src.client import HLTVClient
from src.config import HLTVConfig
from src.utils.logger import setup_logger

# ═══════════════════════════════════════════════════════════════════
# Legal disclaimer — printed once at CLI startup
_LEGAL_DISCLAIMER = """
================================================================================
                    HLTV API -- Legal Notice

  This tool is for educational and research purposes only.
  HLTV.org is a registered trademark. Not affiliated with or endorsed by HLTV.org.

  - Respect robots.txt and rate limits
  - Do not use scraped data for commercial purposes
  - The author assumes no liability for misuse
  - Use at your own risk
================================================================================"""

app = typer.Typer(
    name="hltv",
    help="HLTV.org unofficial scraper - fetch CS2 match data, team info, player stats, and more.",
    add_completion=False,
)

# Shared state
_client: HLTVClient | None = None
_output_format: str = "json"


class OutputFormat(str, Enum):
    """Output format options."""
    JSON = "json"
    PRETTY = "pretty"


def _get_client(config_path: str | None = None) -> HLTVClient:
    """Get or create the shared HLTV client."""
    global _client
    if _client is None:
        config = HLTVConfig.load(config_path)
        setup_logger(config.logging)
        _client = HLTVClient(config)
    return _client


def _output(data: Any, fmt: str = "json") -> None:
    """Print data in the specified format."""
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    elif isinstance(data, list):
        data = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            for item in data
        ]
    elif isinstance(data, dict):
        data = {
            k: v.model_dump(mode="json") if hasattr(v, "model_dump") else v
            for k, v in data.items()
        }

    if fmt == "pretty":
        typer.echo(json.dumps(data, indent=2, default=str))
    else:
        typer.echo(json.dumps(data, default=str))


# ── Config ──────────────────────────────────────────────────────────


@app.callback()
def main(
    config: Annotated[Optional[str], typer.Option("--config", "-c", help="Path to config YAML file")] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Enable verbose output")] = False,
    output: Annotated[OutputFormat, typer.Option("--output", "-o", help="Output format")] = OutputFormat.JSON,
) -> None:
    """HLTV.org scraper CLI."""
    global _output_format
    _output_format = output.value
    # Print legal disclaimer once
    typer.echo(_LEGAL_DISCLAIMER, err=True)
    # Defer client init until first actual command to speed up --help
    if "--help" not in sys.argv and "-h" not in sys.argv:
        _get_client(config)


# ── Matches ─────────────────────────────────────────────────────────


@app.command()
def upcoming() -> None:
    """Fetch upcoming matches."""
    from src.endpoints.matches import MatchesEndpoint
    client = _get_client()
    matches = asyncio.run(MatchesEndpoint(client).get_upcoming())
    _output(matches, _output_format)


@app.command()
def results(
    page: Annotated[int, typer.Option("--page", "-p", help="Page number")] = 1,
    start_date: Annotated[Optional[str], typer.Option("--start-date", "-s", help="Start date (YYYY-MM-DD)")] = None,
    end_date: Annotated[Optional[str], typer.Option("--end-date", "-e", help="End date (YYYY-MM-DD)")] = None,
) -> None:
    """Fetch historical match results."""
    from src.endpoints.results import ResultsEndpoint
    client = _get_client()
    matches = asyncio.run(
        ResultsEndpoint(client).get_results(
            page=page,
            start_date=start_date,
            end_date=end_date,
        )
    )
    _output(matches, _output_format)


@app.command()
def match(
    match_id: Annotated[int, typer.Argument(help="HLTV match ID")],
) -> None:
    """Fetch detailed match information."""
    from src.endpoints.matches import MatchesEndpoint
    client = _get_client()
    detail = asyncio.run(MatchesEndpoint(client).get_detail(match_id))
    _output(detail, _output_format)


# ── Teams ───────────────────────────────────────────────────────────


@app.command()
def ranking() -> None:
    """Fetch world team ranking."""
    from src.endpoints.teams import TeamsEndpoint
    client = _get_client()
    rank = asyncio.run(TeamsEndpoint(client).get_ranking())
    _output(rank, _output_format)


@app.command()
def team(
    team_id: Annotated[int, typer.Argument(help="HLTV team ID")],
) -> None:
    """Fetch team details."""
    from src.endpoints.teams import TeamsEndpoint
    client = _get_client()
    detail = asyncio.run(TeamsEndpoint(client).get_detail(team_id))
    _output(detail, _output_format)


@app.command()
def roster(
    team_id: Annotated[int, typer.Argument(help="HLTV team ID")],
) -> None:
    """Fetch team roster."""
    from src.endpoints.teams import TeamsEndpoint
    client = _get_client()
    players = asyncio.run(TeamsEndpoint(client).get_roster(team_id))
    _output(players, _output_format)


# ── Players ─────────────────────────────────────────────────────────


@app.command()
def player(
    player_id: Annotated[int, typer.Argument(help="HLTV player ID")],
) -> None:
    """Fetch player details and statistics."""
    from src.endpoints.players import PlayersEndpoint
    client = _get_client()
    detail = asyncio.run(PlayersEndpoint(client).get_detail(player_id))
    _output(detail, _output_format)


@app.command()
def top_players(
    period: Annotated[str, typer.Option("--period", "-p", help="Time period: last3months, last6months, last12months, alltime, currentyear, bigevents")] = "last3months",
) -> None:
    """Fetch top player rankings."""
    from src.endpoints.players import PlayersEndpoint
    client = _get_client()
    response = asyncio.run(PlayersEndpoint(client).get_top_players(period))
    _output(response, _output_format)


# ── Events ──────────────────────────────────────────────────────────


@app.command()
def events(
    ongoing: Annotated[bool, typer.Option("--ongoing", "-o", help="Only ongoing events")] = False,
) -> None:
    """Fetch event listings."""
    from src.endpoints.events import EventsEndpoint
    client = _get_client()
    ep = EventsEndpoint(client)
    data = asyncio.run(ep.get_ongoing() if ongoing else ep.get_events())
    _output(data, _output_format)


@app.command()
def event(
    event_id: Annotated[int, typer.Argument(help="HLTV event ID")],
) -> None:
    """Fetch event details."""
    from src.endpoints.events import EventsEndpoint
    client = _get_client()
    detail = asyncio.run(EventsEndpoint(client).get_detail(event_id))
    _output(detail, _output_format)


# ── News ────────────────────────────────────────────────────────────


@app.command()
def news(
    offset: Annotated[int, typer.Option("--offset", help="Pagination offset")] = 0,
    limit: Annotated[int, typer.Option("--limit", "-l", help="Items per page")] = 30,
) -> None:
    """Fetch news articles."""
    from src.endpoints.news import NewsEndpoint
    client = _get_client()
    articles = asyncio.run(NewsEndpoint(client).get_news(offset=offset, limit=limit))
    _output(articles, _output_format)


# ── Search ──────────────────────────────────────────────────────────


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="Search query")],
) -> None:
    """Search HLTV for players, teams, matches, events."""
    from src.endpoints.search import SearchEndpoint
    client = _get_client()
    results = asyncio.run(SearchEndpoint(client).search(query))
    _output(results, _output_format)


# ── Utility ─────────────────────────────────────────────────────────


@app.command()
def clear_cache() -> None:
    """Clear the HTTP response cache."""
    client = _get_client()
    client.clear_cache()
    typer.echo("Cache cleared.")


@app.command()
def info() -> None:
    """Show scraper configuration info."""
    client = _get_client()
    config = client.config
    _output(
        {
            "base_url": config.base_url,
            "mode": config.client.mode,
            "cache_backend": config.cache.backend,
            "rate_limiting": {
                "enabled": config.rate_limit.enabled,
                "min_delay": config.rate_limit.min_delay,
                "max_delay": config.rate_limit.max_delay,
            },
            "retry": {
                "max_retries": config.client.max_retries,
                "retry_delay": config.client.retry_delay,
            },
            "user_agent_rotation": config.client.user_agent_rotation,
            "curl_impersonation": config.client.curl_impersonate,
        },
        _output_format,
    )


def entry() -> None:
    """Entry point for the CLI."""
    app()


# ── Demos ────────────────────────────────────────────────────────────


@app.command()
def demos(
    match_id: Annotated[int, typer.Argument(help="HLTV match ID")],
) -> None:
    """List available demo downloads for a match."""
    from src.endpoints.demos import DemosEndpoint
    client = _get_client()
    demo_list = asyncio.run(DemosEndpoint(client).get_demos(match_id))
    _output(demo_list, _output_format)


@app.command()
def download_demo(
    demo_url: Annotated[str, typer.Argument(help="Demo download URL")],
    output: Annotated[str, typer.Option("--output", "-o", help="Output directory or file path")] = ".",
) -> None:
    """Download a demo file from HLTV."""
    from src.endpoints.demos import DemosEndpoint
    client = _get_client()
    path = asyncio.run(DemosEndpoint(client).download_demo(demo_url, output))
    typer.echo("Downloaded: {}".format(path))


@app.command()
def download_match(
    match_id: Annotated[int, typer.Argument(help="HLTV match ID")],
    output_dir: Annotated[str, typer.Option("--output", "-o", help="Output directory")] = "demos",
) -> None:
    """Download all demos for a match."""
    from src.endpoints.demos import DemosEndpoint
    client = _get_client()
    paths = asyncio.run(DemosEndpoint(client).download_match_demos(match_id, output_dir))
    typer.echo("Downloaded {} demos to {}".format(len(paths), output_dir))


# ── Export ────────────────────────────────────────────────────────────


@app.command()
def convert(
    input_file: Annotated[str, typer.Argument(help="Input JSON file (use '-' for stdin)")],
    output_file: Annotated[str, typer.Option("--output", "-o", help="Output file path")],
    fmt: Annotated[str, typer.Option("--format", "-f", help="Output format: csv or json")] = "csv",
) -> None:
    """Convert scraped JSON data to CSV format.

    Usage:
        python main.py upcoming --output json > data.json
        python main.py convert data.json -o output.csv
    """
    import json
    import csv as csv_mod

    # Read input
    if input_file == "-":
        import sys
        raw = sys.stdin.read()
    else:
        with open(input_file, encoding="utf-8") as f:
            raw = f.read()

    data = json.loads(raw)

    # Flatten list of dicts to CSV
    if isinstance(data, list) and data and isinstance(data[0], dict):
        flat_rows = []
        for item in data:
            flat = _flatten_dict(item)
            flat_rows.append(flat)

        with open(output_file, "w", encoding="utf-8", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=flat_rows[0].keys())
            writer.writeheader()
            writer.writerows(flat_rows)
        typer.echo("Exported {} rows to {}".format(len(flat_rows), output_file))
    else:
        # JSON output
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=2, default=str))
        typer.echo("Exported to {}".format(output_file))


def _flatten_dict(d: dict, parent_key: str = "", sep: str = ".") -> dict[str, str]:
    """Flatten nested dict into single-level dict for CSV export."""
    items: list[tuple[str, str]] = []
    for k, v in d.items():
        new_key = "{}{}{}".format(parent_key, sep, k) if parent_key else k
        if isinstance(v, dict):
            items.extend(_flatten_dict(v, new_key, sep=sep).items())
        elif isinstance(v, list):
            items.append((new_key, str(v)))
        elif v is None:
            items.append((new_key, ""))
        else:
            items.append((new_key, str(v)))
    return dict(items)


# ── v3.0 Operations ────────────────────────────────────────────────


@app.command()
def status() -> None:
    """Show scraper health status, parse rates, and resource usage."""
    client = _get_client()

    # Rate limiter stats
    limiter = client._rate_limiter.get_stats()

    # Parse stats
    from src.utils.parsestats import report_all
    parse_stats = report_all()

    # Build status output
    result: dict[str, Any] = {
        "mode": client.config.client.mode,
        "rate_limiter": limiter,
        "parse_stats": parse_stats,
    }

    # Try to get memory info
    try:
        import psutil
        result["memory"] = {
            "percent": psutil.virtual_memory().percent,
            "used_mb": psutil.virtual_memory().used // (1024 * 1024),
            "total_mb": psutil.virtual_memory().total // (1024 * 1024),
        }
        result["cpu_percent"] = psutil.cpu_percent(interval=0.5)
    except ImportError:
        pass

    # Try warehouse stats
    try:
        from src.warehouse import Warehouse
        from pathlib import Path
        db_path = Path("hltv_data.sqlite")
        if db_path.exists():
            w = Warehouse(str(db_path))
            result["warehouse"] = w.get_stats()
            result["warehouse"]["size_mb"] = db_path.stat().st_size // (1024 * 1024)
    except Exception:
        pass

    _output(result, _output_format)


@app.command()
def cleanup(
    days: Annotated[int, typer.Option("--days", "-d", help="Keep data for N days")] = 90,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show what would be deleted")] = False,
) -> None:
    """Clean up old scraped data and cache."""
    typer.echo("Cleanup: keeping {} days of data".format(days))

    # Warehouse cleanup
    try:
        from src.warehouse import Warehouse
        from pathlib import Path
        db_path = Path("hltv_data.sqlite")
        if db_path.exists():
            old_size = db_path.stat().st_size
            w = Warehouse(str(db_path))
            if not dry_run:
                w.conn.execute(
                    "DELETE FROM matches WHERE match_date < date('now', '-' || ? || ' days')",
                    (days,),
                )
                w.conn.execute(
                    "DELETE FROM rankings_history WHERE snapshot_date < date('now', '-' || ? || ' days')",
                    (days,),
                )
                w.conn.execute("VACUUM")
                w.conn.commit()
            new_size = db_path.stat().st_size
            typer.echo("  Warehouse: {} -> {} bytes".format(old_size, new_size))
    except Exception as e:
        typer.echo("  Warehouse: error - {}".format(e))

    # Cache cleanup
    from src.client import HLTVClient
    if not dry_run:
        _get_client().clear_cache()
    typer.echo("  Cache: cleared")

    typer.echo("Cleanup complete." if not dry_run else "Dry run complete.")


@app.command()
def backup(
    output_dir: Annotated[str, typer.Option("--output", "-o", help="Backup directory")] = "backups",
) -> None:
    """Backup scraped data (warehouse, cache, config)."""
    import shutil
    from datetime import datetime
    from pathlib import Path

    backup_dir = Path(output_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / "hltv_backup_{}".format(timestamp)
    backup_path.mkdir(parents=True, exist_ok=True)

    files_backed = 0

    # Warehouse
    db_path = Path("hltv_data.sqlite")
    if db_path.exists():
        shutil.copy2(str(db_path), str(backup_path / "hltv_data.sqlite"))
        files_backed += 1

    # Config
    for cfg in Path(".").glob("config*.yaml"):
        shutil.copy2(str(cfg), str(backup_path / cfg.name))
        files_backed += 1

    # Logs
    log_dir = Path("logs")
    if log_dir.exists():
        for f in log_dir.glob("*.log*"):
            shutil.copy2(str(f), str(backup_path / f.name))
            files_backed += 1

    typer.echo("Backup saved to: {}".format(backup_path))
    typer.echo("Files backed up: {}".format(files_backed))


if __name__ == "__main__":
    app()
