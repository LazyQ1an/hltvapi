"""
Plugin system for HLTV scraper extensions.

Allows community-contributed parsers, data sources, and processors.

Usage:
    from src.plugins import PluginManager, BasePlugin

    class MyPlugin(BasePlugin):
        name = "my_plugin"
        version = "1.0.0"

        async def on_startup(self, client, warehouse):
            ...

        async def process_match(self, match):
            ...

    manager = PluginManager()
    manager.register(MyPlugin())
    await manager.load_all(client, warehouse)
"""

from __future__ import annotations

from .base import BasePlugin, PluginManager

__all__ = ["BasePlugin", "PluginManager"]
