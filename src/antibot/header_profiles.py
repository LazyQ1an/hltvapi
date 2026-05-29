from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any


@dataclass
class HeaderProfile:
    """Complete browser header profile.

    Headers must form a coherent whole -- mixing headers from different
    browsers (e.g. Chrome UA with Firefox-specific headers) is the easiest
    anti-crawling detection vector.
    """
    name: str
    user_agent: str
    sec_ch_ua: str | None = None
    sec_ch_ua_platform: str | None = None
    sec_ch_ua_mobile: str | None = "?0"
    accept: str | None = (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    )
    accept_language: str | None = "en-US,en;q=0.9"
    accept_encoding: str | None = "gzip, deflate, br, zstd"
    sec_fetch_site: str | None = "same-origin"
    sec_fetch_mode: str | None = "navigate"
    sec_fetch_dest: str | None = "document"
    sec_fetch_user: str | None = "?1"
    upgrade_insecure_requests: str | None = "1"
    dnt: str | None = None
    sec_gpc: str | None = None
    priority: str | None = "u=0, i"
    referer: str | None = "https://www.hltv.org/"

    def to_dict(self, referer: str | None = None) -> dict[str, str]:
        headers: dict[str, str] = {
            "User-Agent": self.user_agent,
        }
        if self.accept:
            headers["Accept"] = self.accept
        if self.accept_language:
            headers["Accept-Language"] = self.accept_language
        if self.accept_encoding:
            headers["Accept-Encoding"] = self.accept_encoding
        headers["Referer"] = referer or (self.referer or "https://www.hltv.org/")
        if self.sec_ch_ua:
            headers["Sec-Ch-Ua"] = self.sec_ch_ua
        if self.sec_ch_ua_platform:
            headers["Sec-Ch-Ua-Platform"] = self.sec_ch_ua_platform
        if self.sec_ch_ua_mobile:
            headers["Sec-Ch-Ua-Mobile"] = self.sec_ch_ua_mobile
        if self.upgrade_insecure_requests:
            headers["Upgrade-Insecure-Requests"] = self.upgrade_insecure_requests
        if self.sec_fetch_site:
            headers["Sec-Fetch-Site"] = self.sec_fetch_site
        if self.sec_fetch_mode:
            headers["Sec-Fetch-Mode"] = self.sec_fetch_mode
        if self.sec_fetch_dest:
            headers["Sec-Fetch-Dest"] = self.sec_fetch_dest
        if self.sec_fetch_user:
            headers["Sec-Fetch-User"] = self.sec_fetch_user
        if self.priority:
            headers["Priority"] = self.priority
        if self.dnt is not None:
            headers["DNT"] = self.dnt
        if self.sec_gpc is not None:
            headers["Sec-GPC"] = self.sec_gpc
        return headers


CHROME_WIN = HeaderProfile(
    name="chrome_win",
    user_agent=(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    sec_ch_ua='"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    sec_ch_ua_platform='"Windows"',
)

CHROME_MAC = HeaderProfile(
    name="chrome_mac",
    user_agent=(
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_3) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    sec_ch_ua='"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    sec_ch_ua_platform='"macOS"',
)

CHROME_LINUX = HeaderProfile(
    name="chrome_linux",
    user_agent=(
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    sec_ch_ua='"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    sec_ch_ua_platform='"Linux"',
)

EDGE_WIN = HeaderProfile(
    name="edge_win",
    user_agent=(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
    ),
    sec_ch_ua='"Microsoft Edge";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    sec_ch_ua_platform='"Windows"',
)

FIREFOX_WIN = HeaderProfile(
    name="firefox_win",
    user_agent=(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:136.0) "
        "Gecko/20100101 Firefox/136.0"
    ),
    accept=(
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "*/*;q=0.8"
    ),
    accept_encoding="gzip, deflate, br",
    dnt="1",
    sec_gpc="1",
    sec_ch_ua=None,
    sec_ch_ua_platform=None,
)

SAFARI_MAC = HeaderProfile(
    name="safari_mac",
    user_agent=(
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_3) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/18.3 Safari/605.1.15"
    ),
    accept=(
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "*/*;q=0.8"
    ),
    accept_encoding="gzip, deflate, br",
    sec_ch_ua=None,
    sec_ch_ua_platform=None,
    sec_fetch_user=None,
    priority=None,
    upgrade_insecure_requests=None,
)


HEADER_PROFILES: list[HeaderProfile] = [
    CHROME_WIN,
    CHROME_MAC,
    CHROME_LINUX,
    EDGE_WIN,
    FIREFOX_WIN,
    SAFARI_MAC,
]


def random_profile() -> HeaderProfile:
    return random.choice(HEADER_PROFILES)


_REFERERS = [
    "https://www.google.com/",
    "https://www.hltv.org/",
    "https://www.hltv.org/matches",
    "https://www.hltv.org/results",
    "https://www.hltv.org/ranking/teams",
    "https://www.hltv.org/events",
    "https://www.reddit.com/r/GlobalOffensive/",
    "https://www.twitch.tv/directory/game/Counter-Strike",
    "https://www.hltv.org/stats",
    "https://www.hltv.org/news",
]

_ACCEPT_LANGUAGES = [
    "en-US,en;q=0.9",
    "en-US,en;q=0.9,fr;q=0.8",
    "en-GB,en;q=0.9,en-US;q=0.8",
    "en;q=0.9",
    "en-US,en;q=0.8,de;q=0.6",
]


def random_referer() -> str:
    return random.choice(_REFERERS)


def random_accept_language() -> str:
    return random.choice(_ACCEPT_LANGUAGES)