from __future__ import annotations

import random
import time as tmod
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class BrowsingHistory:
    """
    单个 session 的浏览历史记录。

    真实用户的浏览行为具有：
    - 路径连贯性：从首页 → 比赛列表 → 比赛详情
    - 回头访问：偶尔回到之前看过的页面
    - 兴趣偏好：某些用户更关注比赛，某些更关注新闻
    - 停留时间：不同页面有不同的阅读时间
    """

    visited_paths: list[str] = field(default_factory=list)
    visit_timestamps: list[float] = field(default_factory=list)
    interest_weights: dict[str, float] = field(default_factory=lambda: {
        "matches": 0.35,
        "results": 0.25,
        "ranking": 0.15,
        "news": 0.10,
        "events": 0.08,
        "players": 0.04,
        "stats": 0.03,
    })
    current_session_depth: int = 0
    max_session_depth: int = 0

    def record_visit(self, path: str) -> None:
        self.visited_paths.append(path)
        self.visit_timestamps.append(tmod.time())
        if len(self.visited_paths) > 200:
            self.visited_paths = self.visited_paths[-100:]
            self.visit_timestamps = self.visit_timestamps[-100:]
        self.current_session_depth += 1
        self.max_session_depth = max(self.max_session_depth, self.current_session_depth)
        self._decay_interests()

    def _decay_interests(self) -> None:
        if self.current_session_depth % 20 != 0:
            return
        for k in self.interest_weights:
            self.interest_weights[k] *= 0.95
        total = sum(self.interest_weights.values())
        if total > 0:
            for k in self.interest_weights:
                self.interest_weights[k] /= total

    def get_recent_paths(self, n: int = 10) -> list[str]:
        return self.visited_paths[-n:]

    def get_last_visit_gap(self) -> float:
        if len(self.visit_timestamps) < 2:
            return 0.0
        return self.visit_timestamps[-1] - self.visit_timestamps[-2]

    def should_return(self) -> bool:
        if len(self.visited_paths) < 3:
            return False
        return random.random() < 0.12

    def get_return_path(self) -> str | None:
        if not self.visited_paths:
            return None
        idx = random.randint(0, min(len(self.visited_paths) - 1, 5))
        return self.visited_paths[idx]

    def reset_session_depth(self) -> None:
        self.current_session_depth = 0


@dataclass
class SessionIdentity:
    """
    一个 session 的完整身份指纹 + 行为画像。

    核心原则：
    1. 一个 session 从创建到退役，只使用一个 identity
    2. identity 包含完整的浏览器指纹一致性
    3. 行为画像让每个 session 像一个有偏好的真实用户
    4. Cookie 生命周期模拟真实浏览器行为
    """

    user_agent: str = ""
    accept_language: str = "en-US,en;q=0.9"
    platform: Literal["win32", "darwin", "linux"] = "win32"
    viewport_width: int = 1920
    viewport_height: int = 1080
    timezone: str = "America/New_York"
    locale: str = "en-US"
    hardware_concurrency: int = 8
    device_memory: int = 8

    tls_version: str = "chrome124"
    impersonate_version: str = "chrome124"

    sec_ch_ua: str = ""
    sec_ch_ua_platform: str = ""
    sec_ch_ua_mobile: str = "?0"
    sec_ch_ua_full_version_list: str | None = None

    browser_type: Literal["chrome", "firefox", "safari", "edge"] = "chrome"

    browsing: BrowsingHistory = field(default_factory=BrowsingHistory)

    cookie_birth_time: dict[str, float] = field(default_factory=dict)
    session_start_time: float = field(default_factory=tmod.time)

    screen_color_depth: int = 24
    do_not_track: str | None = None
    connection_type: str = "4g"
    gpu_vendor: str = "Google Inc. (NVIDIA)"
    gpu_renderer: str = "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 SUPER Direct3D11 vs_5_0 ps_5_0)"

    @classmethod
    def random(cls, platform: str | None = None) -> SessionIdentity:
        if platform is None:
            platform = random.choice(["win32", "darwin", "linux"])

        browser_type = random.choices(
            ["chrome", "edge", "firefox", "safari"],
            weights=[0.62, 0.15, 0.13, 0.10],
        )[0]

        if browser_type == "safari" and platform != "darwin":
            browser_type = "chrome"
        if browser_type == "edge" and platform == "darwin":
            browser_type = "chrome"

        chrome_ver = random.choice(["124", "131", "136", "133"])
        firefox_ver = random.choice(["133", "135", "144", "128"])

        ua, sec_ch_ua, sec_ch_ua_platform, tz, gpu_vendor, gpu_renderer = cls._build_fingerprint(
            browser_type, platform, chrome_ver, firefox_ver,
        )

        viewport = random.choice([
            (1920, 1080), (1366, 768), (1440, 900),
            (1536, 864), (2560, 1440), (1680, 1050),
            (1280, 720), (3840, 2160),
        ])
        hw_concurrency = random.choice([4, 6, 8, 8, 12, 16])
        device_mem = random.choice([4, 8, 8, 16, 32])
        lang = random.choice([
            "en-US,en;q=0.9",
            "en-US,en;q=0.9,fr;q=0.8",
            "en-GB,en;q=0.9,en-US;q=0.8",
            "en;q=0.9",
            "en-US,en;q=0.8,de;q=0.6",
            "en-US,en;q=0.9,pt;q=0.7",
        ])

        interest_weights = cls._random_interests()

        return cls(
            user_agent=ua,
            accept_language=lang,
            platform=platform,  # type: ignore[arg-type]
            viewport_width=viewport[0],
            viewport_height=viewport[1],
            timezone=tz,
            hardware_concurrency=hw_concurrency,
            device_memory=device_mem,
            tls_version=f"chrome{chrome_ver}" if browser_type in ("chrome", "edge") else f"firefox{firefox_ver}",
            impersonate_version=f"chrome{chrome_ver}" if browser_type in ("chrome", "edge") else f"firefox{firefox_ver}",
            sec_ch_ua=sec_ch_ua,
            sec_ch_ua_platform=sec_ch_ua_platform,
            browser_type=browser_type,  # type: ignore[arg-type]
            browsing=BrowsingHistory(interest_weights=interest_weights),
            do_not_track="1" if browser_type == "firefox" else None,
            gpu_vendor=gpu_vendor,
            gpu_renderer=gpu_renderer,
        )

    @staticmethod
    def _build_fingerprint(
        browser_type: str,
        platform: str,
        chrome_ver: str,
        firefox_ver: str,
    ) -> tuple[str, str, str, str, str, str]:
        if browser_type == "chrome":
            if platform == "win32":
                ua = (
                    f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    f"(KHTML, like Gecko) Chrome/{chrome_ver}.0.0.0 Safari/537.36"
                )
                sec_ch_ua = (
                    f'"Google Chrome";v="{chrome_ver}", "Chromium";v="{chrome_ver}", '
                    f'"Not_A Brand";v="24"'
                )
                sec_ch_ua_platform = '"Windows"'
                tz = random.choice(["America/New_York", "America/Chicago", "America/Los_Angeles", "Europe/London"])
                gpu_vendor = "Google Inc. (NVIDIA)"
                gpu_renderer = random.choice([
                    "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 SUPER Direct3D11 vs_5_0 ps_5_0)",
                    "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0)",
                    "ANGLE (NVIDIA, NVIDIA GeForce RTX 4070 Direct3D11 vs_5_0 ps_5_0)",
                ])
            elif platform == "darwin":
                ua = (
                    f"Mozilla/5.0 (Macintosh; Intel Mac OS X 15_3) AppleWebKit/537.36 "
                    f"(KHTML, like Gecko) Chrome/{chrome_ver}.0.0.0 Safari/537.36"
                )
                sec_ch_ua = (
                    f'"Google Chrome";v="{chrome_ver}", "Chromium";v="{chrome_ver}", '
                    f'"Not_A Brand";v="24"'
                )
                sec_ch_ua_platform = '"macOS"'
                tz = random.choice(["America/New_York", "America/Los_Angeles", "Europe/London"])
                gpu_vendor = "Apple Inc."
                gpu_renderer = "Apple M1"
            else:
                ua = (
                    f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    f"(KHTML, like Gecko) Chrome/{chrome_ver}.0.0.0 Safari/537.36"
                )
                sec_ch_ua = (
                    f'"Google Chrome";v="{chrome_ver}", "Chromium";v="{chrome_ver}", '
                    f'"Not_A Brand";v="24"'
                )
                sec_ch_ua_platform = '"Linux"'
                tz = "UTC"
                gpu_vendor = "Mesa"
                gpu_renderer = "Mesa Intel(R) UHD Graphics 630"

        elif browser_type == "edge":
            ua = (
                f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                f"(KHTML, like Gecko) Chrome/{chrome_ver}.0.0.0 Safari/537.36 Edg/{chrome_ver}.0.0.0"
            )
            sec_ch_ua = (
                f'"Microsoft Edge";v="{chrome_ver}", "Chromium";v="{chrome_ver}", '
                f'"Not_A Brand";v="24"'
            )
            sec_ch_ua_platform = '"Windows"'
            tz = random.choice(["America/New_York", "America/Chicago"])
            gpu_vendor = "Google Inc. (NVIDIA)"
            gpu_renderer = "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 SUPER Direct3D11 vs_5_0 ps_5_0)"

        elif browser_type == "firefox":
            if platform == "win32":
                ua = (
                    f"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:{firefox_ver}.0) "
                    f"Gecko/20100101 Firefox/{firefox_ver}.0"
                )
            elif platform == "darwin":
                ua = (
                    f"Mozilla/5.0 (Macintosh; Intel Mac OS X 15.3; rv:{firefox_ver}.0) "
                    f"Gecko/20100101 Firefox/{firefox_ver}.0"
                )
            else:
                ua = (
                    f"Mozilla/5.0 (X11; Linux x86_64; rv:{firefox_ver}.0) "
                    f"Gecko/20100101 Firefox/{firefox_ver}.0"
                )
            sec_ch_ua = ""
            sec_ch_ua_platform = ""
            tz = random.choice(["America/New_York", "Europe/Berlin", "UTC"])
            gpu_vendor = ""
            gpu_renderer = ""

        elif browser_type == "safari":
            ua = (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_3) AppleWebKit/605.1.15 "
                "(KHTML, like Gecko) Version/18.3 Safari/605.1.15"
            )
            sec_ch_ua = ""
            sec_ch_ua_platform = ""
            tz = random.choice(["America/New_York", "America/Los_Angeles"])
            gpu_vendor = "Apple Inc."
            gpu_renderer = "Apple M1"

        else:
            ua = ""
            sec_ch_ua = ""
            sec_ch_ua_platform = ""
            tz = "UTC"
            gpu_vendor = ""
            gpu_renderer = ""

        return ua, sec_ch_ua, sec_ch_ua_platform, tz, gpu_vendor, gpu_renderer

    @staticmethod
    def _random_interests() -> dict[str, float]:
        base = {
            "matches": 0.35,
            "results": 0.25,
            "ranking": 0.15,
            "news": 0.10,
            "events": 0.08,
            "players": 0.04,
            "stats": 0.03,
        }
        keys = list(base.keys())
        for k in keys:
            base[k] *= random.uniform(0.5, 1.5)
        total = sum(base.values())
        return {k: v / total for k, v in base.items()}

    def build_headers(self, referer: str | None = None) -> dict[str, str]:
        """
        基于当前 identity 构建完整一致的 HTTP headers。

        关键：headers 必须与 identity 的 browser_type / platform 完全一致，
        不能混用不同浏览器的特征。
        """
        headers: dict[str, str] = {
            "User-Agent": self.user_agent,
            "Accept-Language": self.accept_language,
            "Accept-Encoding": self._get_accept_encoding(),
        }

        if referer:
            headers["Referer"] = referer
        elif self.browsing.visited_paths:
            last = self.browsing.visited_paths[-1]
            headers["Referer"] = f"https://www.hltv.org{last}"
        else:
            headers["Referer"] = "https://www.hltv.org/"

        if self.browser_type in ("chrome", "edge"):
            headers["Accept"] = (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8"
            )
            headers["Sec-Ch-Ua"] = self.sec_ch_ua
            headers["Sec-Ch-Ua-Mobile"] = self.sec_ch_ua_mobile
            headers["Sec-Ch-Ua-Platform"] = self.sec_ch_ua_platform
            headers["Sec-Fetch-Site"] = "same-origin"
            headers["Sec-Fetch-Mode"] = "navigate"
            headers["Sec-Fetch-Dest"] = "document"
            headers["Sec-Fetch-User"] = "?1"
            headers["Upgrade-Insecure-Requests"] = "1"
            headers["Priority"] = "u=0, i"
        elif self.browser_type == "firefox":
            headers["Accept"] = (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "*/*;q=0.8"
            )
            headers["Upgrade-Insecure-Requests"] = "1"
            if self.do_not_track:
                headers["DNT"] = self.do_not_track
            headers["Sec-GPC"] = "1"
            headers["Sec-Fetch-Dest"] = "document"
            headers["Sec-Fetch-Mode"] = "navigate"
            headers["Sec-Fetch-Site"] = "same-origin"
            headers["Sec-Fetch-User"] = "?1"
        elif self.browser_type == "safari":
            headers["Accept"] = (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "*/*;q=0.8"
            )
            headers["Accept-Encoding"] = "gzip, deflate, br"
            headers["Sec-Fetch-Dest"] = "document"
            headers["Sec-Fetch-Mode"] = "navigate"
            headers["Sec-Fetch-Site"] = "same-origin"

        return headers

    def _get_accept_encoding(self) -> str:
        if self.browser_type in ("chrome", "edge"):
            return "gzip, deflate, br, zstd"
        return "gzip, deflate, br"

    def get_natural_referer(self, target_path: str) -> str:
        """
        根据目标路径和浏览历史，生成自然的 Referer。

        模拟真实用户的导航路径：
        - 从首页进入列表页
        - 从列表页进入详情页
        - 偶尔从搜索引擎来
        """
        recent = self.browsing.get_recent_paths(5)

        if recent and random.random() < 0.75:
            return f"https://www.hltv.org{recent[-1]}"

        referer_map = {
            "/matches/": "https://www.hltv.org/matches",
            "/results/": "https://www.hltv.org/results",
            "/ranking/": "https://www.hltv.org/ranking/teams",
            "/news/": "https://www.hltv.org/news",
            "/events/": "https://www.hltv.org/events",
            "/stats/": "https://www.hltv.org/stats",
            "/player/": "https://www.hltv.org/stats/players",
            "/team/": "https://www.hltv.org/stats/teams",
        }

        for path_prefix, ref in referer_map.items():
            if target_path.startswith(path_prefix):
                if random.random() < 0.85:
                    return ref
                return random.choice([
                    "https://www.google.com/",
                    "https://www.hltv.org/",
                ])

        if random.random() < 0.6:
            return "https://www.hltv.org/"
        return random.choice([
            "https://www.google.com/",
            "https://www.reddit.com/r/GlobalOffensive/",
        ])

    def age_seconds(self) -> float:
        return tmod.time() - self.session_start_time
