"""
HLTV Scraper - Entry point.

Provides unified access to both CLI and API interfaces.

Usage:
    # CLI mode
    python main.py matches upcoming
    python main.py team 6667

    # API mode
    python main.py serve
"""

from __future__ import annotations

import sys


def main() -> None:
    """Main entry point: dispatches to CLI or API server.

    If the first argument is "serve", starts the FastAPI server.
    Otherwise, delegates to the Typer CLI.
    """
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        _run_server()
    else:
        _run_cli()


def _run_cli() -> None:
    """Run the Typer CLI."""
    from cli import app
    app()


def _run_server() -> None:
    """Run the FastAPI server via uvicorn."""
    import uvicorn
    from api import app

    host = "0.0.0.0"
    port = 8000

    # Allow overriding via environment
    import os
    host = os.environ.get("HLTV_HOST", host)
    port = int(os.environ.get("HLTV_PORT", str(port)))

    print(f"Starting HLTV Scraper API at http://{host}:{port}")
    print("Docs available at http://{0}:{1}/docs".format(host, port))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
