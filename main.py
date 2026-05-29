"""
HLTV Scraper — Entry point.

Three modes of operation:
  python main.py demo           Quick demo: fetch a page with stealth mode
  python main.py serve          Start FastAPI server (for Discord bots, etc.)
  python main.py <command>      CLI mode (matches, teams, players, ranking, etc.)

Direct usage example:
  import asyncio
  from src.client import HLTVClient

  async def main():
      async with HLTVClient(mode="stealth") as client:
          html = await client.get("https://www.hltv.org/matches")
          print(f"Fetched {len(html)} bytes")

  asyncio.run(main())
"""

from __future__ import annotations

import asyncio
import sys


def main() -> None:
    """Main entry point: dispatches to demo, CLI, or API server."""
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        _run_server()
    elif len(sys.argv) > 1 and sys.argv[1] == "demo":
        asyncio.run(_run_demo())
    else:
        _run_cli()


async def _run_demo() -> None:
    """Quick demo: fetch a matches page and print stats."""
    from src.client import HLTVClient
    from src.settings import load_settings

    settings = load_settings()
    print(f"HLTV Scraper v6.0 — mode={settings.mode}")
    print(f"Profiles: {settings.profile.count}, "
          f"Rate: {settings.rate_limit.requests_per_hour}/h, "
          f"{settings.rate_limit.requests_per_day}/day")
    print()

    async with HLTVClient(settings=settings) as client:
        print("Fetching https://www.hltv.org/matches ...")
        html = await client.get("https://www.hltv.org/matches")
        print(f"  OK — {len(html):,} bytes received")

        # Show stats
        stats = client.get_stats()
        print()
        print("Client stats:")
        for key, val in stats.items():
            print(f"  {key}: {val}")

        # Cookie bridge status
        if client.cookie_bridge:
            cf = client.cookie_bridge.get_cf_clearance()
            print(f"  cf_clearance: {'present' if cf else 'none'}")

        if client.profiles:
            print(f"  active profile: {client.profiles.current.name if client.profiles.current else 'none'}")


def _run_cli() -> None:
    """Run the Typer CLI."""
    from cli import app
    app()


def _run_server() -> None:
    """Run the FastAPI server via uvicorn."""
    import uvicorn
    from api import app

    import os
    host = os.environ.get("HLTV_HOST", "0.0.0.0")
    port = int(os.environ.get("HLTV_PORT", "8000"))

    print(f"Starting HLTV Scraper API at http://{host}:{port}")
    print(f"Docs at http://{host}:{port}/docs")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
