from __future__ import annotations

import random
import time as tmod
from typing import Any


_NAVIGATION_GRAPH: dict[str, dict[str, float]] = {
    "home": {
        "matches": 0.30, "results": 0.20, "ranking": 0.15,
        "news": 0.12, "events": 0.10, "stats": 0.08, "home": 0.05,
    },
    "matches": {
        "match_detail": 0.55, "matches": 0.15, "home": 0.10,
        "results": 0.10, "events": 0.10,
    },
    "match_detail": {
        "matches": 0.25, "team_detail": 0.25, "player_detail": 0.20,
        "match_detail": 0.15, "results": 0.15,
    },
    "results": {
        "match_detail": 0.45, "results": 0.20, "home": 0.15,
        "ranking": 0.10, "matches": 0.10,
    },
    "ranking": {
        "team_detail": 0.40, "ranking": 0.20, "home": 0.15,
        "matches": 0.15, "stats": 0.10,
    },
    "team_detail": {
        "player_detail": 0.30, "matches": 0.20, "team_detail": 0.15,
        "ranking": 0.15, "results": 0.10, "stats": 0.10,
    },
    "player_detail": {
        "team_detail": 0.30, "matches": 0.20, "player_detail": 0.15,
        "stats": 0.15, "ranking": 0.10, "results": 0.10,
    },
    "news": {
        "news_detail": 0.50, "news": 0.20, "home": 0.15,
        "matches": 0.15,
    },
    "news_detail": {
        "news": 0.30, "matches": 0.25, "home": 0.20,
        "team_detail": 0.15, "player_detail": 0.10,
    },
    "events": {
        "event_detail": 0.45, "events": 0.20, "home": 0.15,
        "matches": 0.20,
    },
    "event_detail": {
        "matches": 0.30, "team_detail": 0.25, "events": 0.20,
        "results": 0.15, "home": 0.10,
    },
    "stats": {
        "player_detail": 0.30, "team_detail": 0.25, "stats": 0.15,
        "home": 0.15, "ranking": 0.15,
    },
}

for _page_type in _NAVIGATION_GRAPH:
    _NAVIGATION_GRAPH[_page_type].setdefault("search", 0.03)
    _NAVIGATION_GRAPH[_page_type].setdefault("refresh", 0.05)
    _NAVIGATION_GRAPH[_page_type].setdefault("external", 0.02)

_PAGE_READ_TIMES: dict[str, tuple[float, float]] = {
    "home": (3.0, 8.0),
    "matches": (2.0, 5.0),
    "match_detail": (8.0, 30.0),
    "results": (2.0, 6.0),
    "ranking": (3.0, 10.0),
    "team_detail": (5.0, 20.0),
    "player_detail": (5.0, 20.0),
    "news": (2.0, 5.0),
    "news_detail": (10.0, 45.0),
    "events": (2.0, 5.0),
    "event_detail": (5.0, 15.0),
    "stats": (5.0, 15.0),
    "search": (2.0, 5.0),
    "refresh": (1.0, 3.0),
    "external": (5.0, 15.0),
}


class HumanRequestPattern:
    """
    模拟真实用户访问模式的请求间隔生成器 v2。

    核心升级：
    1. 马尔可夫链浏览路径 —— 模拟真实用户的页面跳转概率
    2. 会话状态机 —— 完整的"进入 → 浏览 → 阅读 → 离开"生命周期
    3. 页面阅读时间 —— 不同类型页面有不同的停留时间
    4. 滚动行为模拟 —— 长页面需要更多时间
    5. 会话疲劳 —— 长时间浏览后逐渐变慢
    6. 真实日间模式 —— 更精细的时段分布
    """

    def __init__(
        self,
        burst_min: int = 3,
        burst_max: int = 8,
        burst_delay_min: float = 1.0,
        burst_delay_max: float = 3.0,
        rest_delay_min: float = 30.0,
        rest_delay_max: float = 90.0,
        active_hour_start: int = 8,
        active_hour_end: int = 23,
    ) -> None:
        self._burst_min = burst_min
        self._burst_max = burst_max
        self._burst_delay_min = burst_delay_min
        self._burst_delay_max = burst_delay_max
        self._rest_delay_min = rest_delay_min
        self._rest_delay_max = rest_delay_max
        self._active_start = active_hour_start
        self._active_end = active_hour_end

        self._requests_in_burst = 0
        self._current_burst_size = random.randint(burst_min, burst_max)
        self._total_requests = 0
        self._reset_time = tmod.time()

        self._recent_urls: list[str] = []

        self._current_page_type: str = "home"
        self._session_state: str = "browsing"
        self._session_start: float = tmod.time()
        self._pages_in_session: int = 0
        self._last_navigation_time: float = tmod.time()

        self._fatigue_level: float = 0.0

    async def next_delay(self, url: str | None = None) -> float:
        self._total_requests += 1
        self._pages_in_session += 1

        self._update_page_type(url)
        self._update_fatigue()

        read_time = self._calculate_read_time()

        if self._requests_in_burst >= self._current_burst_size:
            self._requests_in_burst = 1
            self._current_burst_size = random.randint(
                self._burst_min, self._burst_max,
            )
            delay = self._get_rest_delay() + read_time
            self._session_state = "resting"
        else:
            self._requests_in_burst += 1
            delay = self._get_burst_delay() + read_time * 0.3
            self._session_state = "browsing"

        hour_factor = self._get_hour_factor()
        delay *= hour_factor

        delay *= (1.0 + self._fatigue_level * 0.5)

        if self._total_requests % random.randint(20, 40) == 0:
            delay += random.uniform(5.0, 15.0)

        if random.random() < 0.05:
            delay += random.uniform(2.0, 8.0)

        if url:
            self._recent_urls.append(url)
            if len(self._recent_urls) > 100:
                self._recent_urls.pop(0)

        self._last_navigation_time = tmod.time()

        return delay

    def _update_page_type(self, url: str | None = None) -> None:
        if url:
            self._current_page_type = self._classify_url(url)
        else:
            transitions = _NAVIGATION_GRAPH.get(self._current_page_type, {})
            if transitions:
                pages = list(transitions.keys())
                weights = list(transitions.values())
                self._current_page_type = random.choices(pages, weights=weights)[0]

    def _classify_url(self, url: str) -> str:
        path = url.lower()
        if "/search" in path:
            return "search"
        if "/matches/" in path and path.count("/") > 3:
            return "match_detail"
        if "/matches" in path:
            return "matches"
        if "/results/" in path and path.count("/") > 3:
            return "match_detail"
        if "/results" in path:
            return "results"
        if "/ranking" in path:
            return "ranking"
        if "/team/" in path:
            return "team_detail"
        if "/player/" in path:
            return "player_detail"
        if "/news/" in path and path.count("/") > 3:
            return "news_detail"
        if "/news" in path:
            return "news"
        if "/events/" in path and path.count("/") > 3:
            return "event_detail"
        if "/events" in path:
            return "events"
        if "/stats" in path:
            return "stats"
        return "home"

    def _calculate_read_time(self) -> float:
        time_range = _PAGE_READ_TIMES.get(self._current_page_type, (3.0, 10.0))
        base = random.uniform(time_range[0], time_range[1])

        if self._session_state == "resting":
            base *= 0.3

        return base

    def _update_fatigue(self) -> None:
        session_duration = tmod.time() - self._session_start
        self._fatigue_level = min(1.0, session_duration / 3600.0)

        if session_duration > 1800 and random.random() < 0.1:
            self._session_start = tmod.time()
            self._pages_in_session = 0
            self._fatigue_level = 0.0

    def suggest_next_path(self) -> str | None:
        """
        基于马尔可夫链，建议下一个应该访问的路径类型。
        用于请求调度引擎实现路径连贯性。
        """
        transitions = _NAVIGATION_GRAPH.get(self._current_page_type, {})
        if not transitions:
            return None
        pages = list(transitions.keys())
        weights = list(transitions.values())
        return random.choices(pages, weights=weights)[0]

    def _get_burst_delay(self) -> float:
        return random.uniform(self._burst_delay_min, self._burst_delay_max)

    def _get_rest_delay(self) -> float:
        return random.uniform(self._rest_delay_min, self._rest_delay_max)

    def _get_hour_factor(self) -> float:
        hour = tmod.localtime().tm_hour
        if self._active_start <= hour < self._active_end:
            if 10 <= hour <= 14:
                return 0.9
            if 19 <= hour <= 22:
                return 0.85
            return 1.0

        if 0 <= hour < 3:
            return random.uniform(3.0, 8.0)
        if 3 <= hour < 6:
            return random.uniform(5.0, 10.0)
        return random.uniform(2.0, 4.0)

    def should_skip(self) -> bool:
        return random.random() < 0.03

    def get_reset_status(self) -> bool:
        if tmod.time() - self._reset_time > 600:
            self._requests_in_burst = self._current_burst_size
            self._reset_time = tmod.time()
            return True
        return False


    def get_warmup_paths(self, target_url: str | None = None, count: int = 3) -> list[str]:
        """
        Generate a natural warmup browsing path before visiting the target.

        Simulates: homepage -> listing page -> target detail page.

        Args:
            target_url: The ultimate destination URL.
            count: Number of warmup URLs to generate (1-5).

        Returns:
            List of URLs in natural browsing order.
        """
        count = max(1, min(count, 5))
        target_type = self._classify_url(target_url) if target_url else "home"
        warmup: list[str] = []

        # Always start with homepage
        warmup.append("https://www.hltv.org/")

        if count >= 2:
            # Pick a natural intermediate page based on target type
            if target_type in ("match_detail", "results", "match_detail"):
                warmup.append("https://www.hltv.org/results")
            elif target_type in ("team_detail", "ranking"):
                warmup.append("https://www.hltv.org/ranking")
            elif target_type in ("player_detail", "stats"):
                warmup.append("https://www.hltv.org/stats")
            elif target_type in ("news_detail", "news"):
                warmup.append("https://www.hltv.org/")
            elif target_type in ("event_detail", "events"):
                warmup.append("https://www.hltv.org/events")
            else:
                warmup.append("https://www.hltv.org/matches")

        if count >= 3 and target_type not in ("home", "search"):
            warmup.append(self._pick_related_page(target_type))

        return warmup[:count]

    def _pick_related_page(self, target_type: str) -> str:
        """Pick a semantically-related page for the third warmup hop."""
        related: dict[str, list[str]] = {
            "match_detail": [
                "https://www.hltv.org/results",
                "https://www.hltv.org/events",
            ],
            "player_detail": [
                "https://www.hltv.org/stats",
                "https://www.hltv.org/ranking",
            ],
            "team_detail": [
                "https://www.hltv.org/ranking",
                "https://www.hltv.org/matches",
            ],
            "news_detail": [
                "https://www.hltv.org/",
                "https://www.hltv.org/results",
            ],
            "event_detail": [
                "https://www.hltv.org/matches",
                "https://www.hltv.org/results",
            ],
        }
        pool = related.get(target_type, ["https://www.hltv.org/matches"])
        return random.choice(pool)

    def get_stats(self) -> dict[str, Any]:
        return {
            "burst_position": f"{self._requests_in_burst}/{self._current_burst_size}",
            "total_requests": self._total_requests,
            "recent_urls": len(self._recent_urls),
            "current_hour_factor": self._get_hour_factor(),
            "current_page_type": self._current_page_type,
            "session_state": self._session_state,
            "fatigue_level": round(self._fatigue_level, 2),
            "pages_in_session": self._pages_in_session,
        }
