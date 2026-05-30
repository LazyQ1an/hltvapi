"""
Cross-mode cookie synchronization. NG1.0

Enhanced with:
- Real-time cookie freshness tracking
- Age-based expiration (auto-drop stale cookies)
- Bulk sync to light mode session on every request
- Disk persistence for cross-process survival
"""

from __future__ import annotations

import json
import logging
import time as tmod
from pathlib import Path
from typing import Any

logger = logging.getLogger("hltv.sync.cookies")

SYNCABLE_COOKIES = {
    "cf_clearance",
    "__cf_bm",
    "cf_chl_rc_m",
    "cf_chl_prog",
    "cf_chl_2",
    "cf_chl_3",
}


class CookieBridge:
    """Bridge cookies between Nodriver (stealth) and curl_cffi (light).

    Enhanced with freshness tracking and auto-expiry.
    """

    def __init__(self, cache_dir: str = ".cache/hltv") -> None:
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._jar: dict[str, str] = {}
        self._birth_times: dict[str, float] = {}
        self._last_harvest: float = 0.0
        self._load_from_disk()

    # ── Harvest from stealth ────────────────────

    def harvest_from_stealth(self, cookies: dict[str, str]) -> int:
        """Extract syncable cookies from Nodriver session."""
        now = tmod.time()
        count = 0
        for key in SYNCABLE_COOKIES:
            if key in cookies:
                self._jar[key] = cookies[key]
                self._birth_times[key] = now
                count += 1

        if count:
            self._last_harvest = now
            self._save_to_disk()
            logger.debug("Harvested %d cookies from stealth", count)

        # Clean up stale cookies
        self._purge_stale(now)

        return count

    def _purge_stale(self, now: float) -> None:
        """Remove cookies that are likely expired."""
        expired = []
        for key, birth in self._birth_times.items():
            age = now - birth
            # cf_clearance typically lives 30-60 min
            if key == "cf_clearance" and age > 3600:
                expired.append(key)
            elif age > 7200:  # Other CF cookies: 2 hours max
                expired.append(key)

        for key in expired:
            self._jar.pop(key, None)
            self._birth_times.pop(key, None)

        if expired:
            logger.debug("Purged %d stale cookies", len(expired))

    def get_cf_clearance(self) -> str | None:
        return self._jar.get("cf_clearance")

    @property
    def has_valid_clearance(self) -> bool:
        if "cf_clearance" not in self._jar:
            return False
        age = tmod.time() - self._birth_times.get("cf_clearance", 0)
        return age < 1800

    @property
    def clearance_age_seconds(self) -> float:
        if "cf_clearance" not in self._birth_times:
            return 99999.0
        return tmod.time() - self._birth_times["cf_clearance"]

    # ── Inject to light ─────────────────────────

    def inject_to_light_headers(self, headers: dict[str, str]) -> dict[str, str]:
        """Add synced cookies to request headers."""
        if not self._jar:
            return headers

        cookie_parts = [f"{k}={v}" for k, v in self._jar.items()]
        if "Cookie" in headers:
            existing = headers["Cookie"]
            # Don't duplicate
            for part in cookie_parts:
                name = part.split("=")[0]
                if name not in existing:
                    existing += "; " + part
            headers["Cookie"] = existing
        else:
            headers["Cookie"] = "; ".join(cookie_parts)

        return headers

    def inject_to_curl_session(self, session: Any) -> None:
        """Inject synced cookies into a curl_cffi session."""
        if not self._jar:
            return
        try:
            for key, value in self._jar.items():
                session.cookies.set(key, value, domain="hltv.org")
        except Exception as e:
            logger.debug("Cookie injection: %s", e)

    # ── Bulk sync ───────────────────────────────

    async def sync_to_light(self, light_session: Any) -> bool:
        """Sync all current cookies to a light mode session.

        Returns True if any cookies were synced.
        """
        if not self._jar or not light_session:
            return False
        self.inject_to_curl_session(light_session)
        return True

    # ── Persistence ─────────────────────────────

    @property
    def _cookie_file(self) -> Path:
        return self._cache_dir / "cookie_bridge.json"

    def _save_to_disk(self) -> None:
        try:
            payload = {
                "cookies": self._jar,
                "birth_times": self._birth_times,
                "last_harvest": self._last_harvest,
                "saved_at": tmod.time(),
            }
            self._cookie_file.write_text(json.dumps(payload, indent=2))
        except Exception as e:
            logger.debug("Cookie bridge save: %s", e)

    def _load_from_disk(self) -> None:
        if self._cookie_file.exists():
            try:
                data = json.loads(self._cookie_file.read_text())
                self._jar = data.get("cookies", {})
                self._birth_times = data.get("birth_times", {})
                self._last_harvest = data.get("last_harvest", 0.0)
                logger.debug(
                    "Loaded %d cookies (age=%ds)",
                    len(self._jar),
                    int(tmod.time() - self._last_harvest),
                )
            except Exception as e:
                logger.debug("Cookie bridge load: %s", e)


__all__ = ["CookieBridge", "SYNCABLE_COOKIES"]
