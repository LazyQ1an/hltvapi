"""
Plugin system base classes and manager.

Design:
- BasePlugin: Abstract base class that all plugins extend
- PluginManager: Discovers, registers, and runs plugins
- Plugins can hook into multiple lifecycle events
- No external dependencies required
"""

from __future__ import annotations

import importlib
import inspect
import logging
from abc import ABC
from pathlib import Path
from typing import Any

logger = logging.getLogger("hltv.plugins")


class BasePlugin(ABC):
    """Abstract base class for all plugins.

    Subclass this and override the hooks you need.
    All hooks are optional — only override what you use.

    Example:
        class LiquipediaPlugin(BasePlugin):
            name = "liquipedia"
            version = "1.0.0"

            async def on_match_fetched(self, match):
                # Enrich match with Liquipedia data
                pass
    """

    name: str = "unnamed"
    """Unique plugin identifier."""

    version: str = "0.1.0"
    """Semantic version."""

    description: str = ""
    """Short description of what this plugin does."""

    # ── Lifecycle hooks ──────────────────────────────────────────

    async def on_startup(self, client: Any, warehouse: Any | None) -> None:
        """Called once when the plugin is loaded.

        Args:
            client: HLTVClient instance.
            warehouse: Warehouse instance (may be None).
        """
        pass

    async def on_shutdown(self) -> None:
        """Called during graceful shutdown."""
        pass

    async def on_match_fetched(self, match: Any) -> Any:
        """Called after a match is fetched.

        Args:
            match: MatchOverview or MatchDetail.

        Returns:
            Enriched match or None.
        """
        return match

    async def on_ranking_fetched(self, ranking: Any) -> Any:
        """Called after ranking is fetched.

        Args:
            ranking: TeamRanking model.

        Returns:
            Enriched ranking or None.
        """
        return ranking

    def get_routes(self) -> list[dict[str, Any]]:
        """Optional FastAPI route definitions.

        Returns:
            List of route dicts with keys: path, methods, handler.
        """
        return []

    def get_dashboard_pages(self) -> list[dict[str, Any]]:
        """Optional Streamlit dashboard pages.

        Returns:
            List of page dicts with keys: name, icon, func.
        """
        return []


class PluginManager:
    """Discovers, loads, and manages plugins.

    Plugins are discovered from:
    1. The 'src/plugins/contrib/' directory
    2. Explicitly registered instances
    """

    def __init__(self) -> None:
        self._plugins: dict[str, BasePlugin] = {}

    def register(self, plugin: BasePlugin) -> None:
        """Register a plugin instance.

        Args:
            plugin: Plugin instance.
        """
        if plugin.name in self._plugins:
            logger.warning("Plugin '%s' already registered, overwriting", plugin.name)
        self._plugins[plugin.name] = plugin
        logger.info("Plugin registered: %s v%s", plugin.name, plugin.version)

    def get(self, name: str) -> BasePlugin | None:
        """Get a registered plugin by name."""
        return self._plugins.get(name)

    @property
    def all(self) -> list[BasePlugin]:
        """Get all registered plugins."""
        return list(self._plugins.values())

    def discover(self, directory: str | None = None) -> int:
        """Auto-discover plugins from a directory.

        Args:
            directory: Path to scan for plugins.
                Defaults to 'src/plugins/contrib/'.

        Returns:
            Number of plugins discovered.
        """
        scan_path = Path(directory or Path(__file__).parent / "contrib")
        if not scan_path.exists():
            return 0

        count = 0
        for entry in scan_path.iterdir():
            if entry.is_file() and entry.suffix == ".py" and not entry.name.startswith("_"):
                try:
                    spec = importlib.util.spec_from_file_location(entry.stem, entry)
                    if spec and spec.loader:
                        mod = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(mod)
                        for _, obj in inspect.getmembers(mod, lambda x: isinstance(x, type) and issubclass(x, BasePlugin) and x is not BasePlugin):
                            plugin = obj()
                            self.register(plugin)
                            count += 1
                except Exception as e:
                    logger.warning("Failed to load plugin %s: %s", entry.name, e)

        return count

    async def load_all(self, client: Any, warehouse: Any | None = None) -> None:
        """Call on_startup for all registered plugins.

        Args:
            client: HLTVClient instance.
            warehouse: Optional warehouse instance.
        """
        for plugin in self._plugins.values():
            try:
                await plugin.on_startup(client, warehouse)
            except Exception as e:
                logger.error("Plugin '%s' on_startup failed: %s", plugin.name, e)

    async def shutdown_all(self) -> None:
        """Gracefully shut down all plugins."""
        for plugin in self._plugins.values():
            try:
                await plugin.on_shutdown()
            except Exception as e:
                logger.warning("Plugin '%s' on_shutdown error: %s", plugin.name, e)

    async def run_match_hooks(self, match: Any) -> Any:
        """Run all plugin match hooks.

        Args:
            match: Match model.

        Returns:
            Processed match.
        """
        result = match
        for plugin in self._plugins.values():
            try:
                result = await plugin.on_match_fetched(result)
            except Exception as e:
                logger.debug("Plugin '%s' match hook failed: %s", plugin.name, e)
        return result
