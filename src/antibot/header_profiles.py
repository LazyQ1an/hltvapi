from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class HeaderProfile:
    """
    完整的浏览器 header 配置。

    核心原则：header 不能单独随机，必须作为一个完整的 profile。
    混用不同浏览器的 header（如 Chrome UA 但 Firefox 特有的 header）是
    最容易被反爬检测到的特征。
    """
    name: str
    user_agent: str
    sec_ch_ua: str | None = None
    sec_ch_ua_platform: str | None = None
    sec_ch_ua_mobile: str = "?0"
    accept: str = (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    )
    accept_language: str = "en-US,en;q=0.9"
    accept_encoding: str = "gzip, deflate, br, zstd"
    sec_fetch_site: str = "same-origin"
    sec_fetch_mode: str = "navigate"
    sec_fetch_dest: str = "document"
    sec_fetch_user: str = "?1"
    upgrade_insecure_requests: str = "1"
    dnt: str | None = None
    sec_gpc: str | None = None
    priority: str = "u=0, i"
    referer: str = "https://www.hltv.org/"

    def to_dict(self, referer: str | None = None) -> dict[str, str]:
        headers: dict[str, str] = {
            "User-Agent": self.user_agent,
            "Accept": self.accept,
            "Accept-Language": self.accept_language,
            "Accept-Encoding": self.accept_encoding,
            "Referer": referer or self.referer,
        }
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


# ── Chrome Profiles ────────────────────────────────────────────

CHROME_WIN = HeaderProfile(
    name="chrome_win",
    user_agent=(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    sec_ch_ua='"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    sec_ch_ua_platform='"Windows"',
    sec_fetch_user="?1",
)

CHROME_MAC = HeaderProfile(
    name="chrome_mac",
    user_agent=(
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_3) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    sec_ch_ua='"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    sec_ch_ua_platform='"macOS"',
    sec_fetch_user="?1",
)

CHROME_LINUX = HeaderProfile(
    name="chrome_linux",
    user_agent=(
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    sec_ch_ua='"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    sec_ch_ua_platform='"Linux"',
    sec_fetch_user="?1",
)

EDGE_WIN = HeaderProfile(
    name="edge_win",
    user_agent=(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
    ),
    sec_ch_ua='"Microsoft Edge";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    sec_ch_ua_platform='"Windows"',
    sec_fetch_user="?1",
)

# ── Firefox Profile ────────────────────────────────────────────

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
    upgrade_insecure_requests="1",
    # Firefox 不使用 Sec-Ch-Ua
    sec_ch_ua=None,
    sec_ch_ua_platform=None,
)

# ── Safari Profile ─────────────────────────────────────────────

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
    # Safari 不使用某些 Sec-* header
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
