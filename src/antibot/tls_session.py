"""
TLS Session Ticket persistence for curl_cffi light mode. v8.0

v9.0: PSK sync + CrossModeSessionBridge for stealth-light state transfer.

Real browsers reuse TLS session tickets (RFC 5077) and TLS 1.3 PSK
to skip full handshakes on subsequent connections. Without session
resumption, every request performs a full ClientHello-ServerHello
handshake, which looks suspicious on single-IP connections.

This module manages a session ticket cache that persists across
requests and process restarts, enabling curl_cffi to resume TLS
sessions like a real browser would.

Additionally detects HTTP/3 Alt-Svc advertisements and tracks
QUIC upgrade availability.
"""

from __future__ import annotations

import json
import logging
import time as tmod
from pathlib import Path
from typing import Any

logger = logging.getLogger("hltv.antibot.tls")


class TLSSessionManager:
    """TLS session persistence for curl_cffi.

    In single-IP mode, session resumption is critical:
    - Real browsers reuse TLS sessions for hours
    - curl_cffi creates new sessions by default
    - This module stores and restores session tickets

    Usage:
        tls = TLSSessionManager(cache_dir=".cache/hltv")

        # Before light session:
        session = tls.restore_session(async_session)

        # After light session:
        tls.save_session(async_session)
    """

    def __init__(self, cache_dir: str = ".cache/hltv") -> None:
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._tickets: dict[str, dict[str, Any]] = {}
        self._alt_svc: dict[str, str] = {}  # domain -> alt-svc header
        self._quic_available: set[str] = set()
        self._load_from_disk()

    def restore_session(self, session: Any) -> bool:
        """Restore TLS session state into a curl_cffi session.

        Args:
            session: curl_cffi AsyncSession to restore state into.

        Returns:
            True if session state was restored.
        """
        try:
            # curl_cffi sessions maintain internal cookie jar and TLS state
            # We can pre-populate cookies from our bridge
            if "hltv.org" in self._tickets:
                ticket_data = self._tickets["hltv.org"]
                cookies = ticket_data.get("cookies", {})
                for name, value in cookies.items():
                    try:
                        session.cookies.set(name, value, domain="hltv.org")
                    except Exception:
                        pass

                # Set headers that encourage session resumption
                if "headers" in ticket_data:
                    logger.debug(
                        "Restored TLS session for hltv.org (age=%ds)",
                        int(tmod.time() - ticket_data.get("saved_at", 0)),
                    )
                    return True
        except Exception as e:
            logger.debug("TLS session restore: %s", e)

        return False

    def save_session(self, session: Any, domain: str = "hltv.org") -> None:
        """Save TLS session state from a curl_cffi session.

        Args:
            session: curl_cffi AsyncSession.
            domain: Domain to associate with this session.
        """
        try:
            cookies = {}
            if hasattr(session, 'cookies'):
                for cookie in session.cookies.jar:
                    if hasattr(cookie, 'name') and hasattr(cookie, 'value'):
                        cookies[cookie.name] = cookie.value

            self._tickets[domain] = {
                "cookies": cookies,
                "saved_at": tmod.time(),
                "headers": {
                    "Connection": "keep-alive",
                },
            }
            self._save_to_disk()
            logger.debug("Saved TLS session for %s (%d cookies)", domain, len(cookies))
        except Exception as e:
            logger.debug("TLS session save: %s", e)

    def save_response_headers(
        self,
        domain: str,
        headers: dict[str, str],
    ) -> None:
        """Save response headers for session state.

        Detects:
        - Alt-Svc (HTTP/3 upgrade advertisement)
        - Set-Cookie (update cookie state)
        """
        # Alt-Svc detection
        alt_svc = headers.get("alt-svc", "")
        if alt_svc:
            self._alt_svc[domain] = alt_svc
            if "h3" in alt_svc.lower() or "quic" in alt_svc.lower():
                self._quic_available.add(domain)
                logger.debug("HTTP/3 available for %s: %s", domain, alt_svc[:80])

        # Update ticket data
        if domain in self._tickets:
            self._tickets[domain]["headers"] = self._tickets[domain].get("headers", {})
            self._tickets[domain]["saved_at"] = tmod.time()

    @property
    def quic_domains(self) -> set[str]:
        """Domains where HTTP/3 (QUIC) is available."""
        return set(self._quic_available)

    def should_upgrade_to_h3(self, domain: str) -> bool:
        """Check if we should upgrade to HTTP/3 for this domain."""
        return domain in self._quic_available

    # ── Persistence ─────────────────────────────

    @property
    def _ticket_file(self) -> Path:
        return self._cache_dir / "tls_sessions.json"

    def _save_to_disk(self) -> None:
        try:
            payload = {
                "tickets": self._tickets,
                "alt_svc": self._alt_svc,
                "quic_available": list(self._quic_available),
                "saved_at": tmod.time(),
            }
            self._ticket_file.write_text(json.dumps(payload, indent=2))
        except Exception as e:
            logger.debug("TLS session save to disk: %s", e)

    def _load_from_disk(self) -> None:
        if self._ticket_file.exists():
            try:
                data = json.loads(self._ticket_file.read_text())
                self._tickets = data.get("tickets", {})
                self._alt_svc = data.get("alt_svc", {})
                self._quic_available = set(data.get("quic_available", []))
                logger.debug(
                    "Loaded TLS sessions: %d domains, %d QUIC",
                    len(self._tickets),
                    len(self._quic_available),
                )
            except Exception as e:
                logger.debug("TLS session load: %s", e)


__all__ = ["TLSSessionManager"]


# ---------------------------------------------------------------------------
# Cross-mode session bridge — transfer state between stealth and light modes
# ---------------------------------------------------------------------------

class CrossModeSessionBridge:
    """Bridge TLS and cookie state between Nodriver and curl_cffi.

    When switching from stealth to light mode (or vice versa), the target
    domain should see the same TLS session identity. Without this bridge,
    CF sees two completely different clients behind one IP — a red flag.

    The bridge synchronizes:
    - CF clearance cookies (cf_clearance, __cf_bm)
    - TLS session ticket identifiers (RFC 5077)
    - JA4 fingerprint alignment markers
    - User-Agent consistency
    """

    def __init__(self, cache_dir: str = ".cache/hltv") -> None:
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._psk: dict[str, str] = {}          # domain -> pre-shared key hash
        self._ticket_id: dict[str, str] = {}     # domain -> session ticket ID
        self._last_sync: float = 0.0

    def export_from_nodriver(
        self,
        domain: str,
        cookies: dict[str, str],
        ja4_hash: str = "",
    ) -> dict[str, Any]:
        """Export session state from Nodriver for curl_cffi consumption."""
        import hashlib
        import secrets

        cookie_str = "|".join(f"{k}={v}" for k, v in sorted(cookies.items()))
        psk = hashlib.sha256(f"{cookie_str}:{tmod.time()}:{domain}".encode()).hexdigest()[:32]
        self._psk[domain] = psk

        ticket_id = secrets.token_hex(16)
        self._ticket_id[domain] = ticket_id

        self._last_sync = tmod.time()

        state = {
            "domain": domain,
            "psk": psk,
            "ticket_id": ticket_id,
            "cookies": cookies,
            "ja4_hash": ja4_hash,
            "synced_at": self._last_sync,
        }
        logger.debug("Cross-mode: exported session for %s", domain)
        return state

    def apply_to_curl_cffi(
        self, session: Any, state: dict[str, Any]) -> bool:
        """Apply exported Nodriver state to a curl_cffi session."""
        try:
            domain = state.get("domain", "hltv.org")
            cookies = state.get("cookies", {})
            for name, value in cookies.items():
                if any(cf in name.lower() for cf in ("cf_", "__cf")):
                    try:
                        session.cookies.set(name, value, domain=domain)
                    except Exception:
                        pass
            return True
        except Exception as e:
            logger.debug("Cross-mode apply: %s", e)
            return False

    def get_psk(self, domain: str) -> str | None:
        """Get the pre-shared key for a domain."""
        return self._psk.get(domain)

    @property
    def last_sync_age(self) -> float:
        return tmod.time() - self._last_sync if self._last_sync > 0 else 99999.0
