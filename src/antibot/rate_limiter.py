from __future__ import annotations

import asyncio
import random
import time as tmod
from collections import deque
from typing import Any


class AdaptiveRateLimiter:
    """
    鍩轰簬婊戝姩鏃堕棿绐楀彛鐨勬櫤鑳介€熺巼闄愬埗鍣?v2銆?
    鏍稿績鍗囩骇锛?    1. 鍝嶅簲鏃堕棿鎰熺煡璋冮€?鈥斺€?鎱㈠搷搴?= 鍙兘琚檺閫燂紝鑷姩闄嶉€?    2. 棰勬祴寮忚皟閫?鈥斺€?鍩轰簬鍘嗗彶 block 棰戠巼棰勬祴鏈潵椋庨櫓锛屾彁鍓嶉檷閫?    3. 娓愯繘鎭㈠ 鈥斺€?block 娑堝け鍚庝笉绔嬪嵆鎭㈠锛岃€屾槸閫愭璇曟帰鎬ф仮澶?    4. 璺緞绾ч檺閫?鈥斺€?涓嶅悓璺緞鐙珛闄愰€燂紙璇︽儏椤?vs 鍒楄〃椤碉級
    5. 鑷€傚簲绐楀彛 鈥斺€?鏍规嵁褰撳墠椋庨櫓绛夌骇鍔ㄦ€佽皟鏁磋娴嬬獥鍙?    6. 绱ф€ュ埗鍔?鈥斺€?杩炵画 block 鏃跺揩閫熻繘鍏ュ喎鍗存湡
    """

    def __init__(
        self,
        min_delay: float = 1.5,
        max_delay: float = 10.0,
        jitter: bool = True,
        requests_per_hour: int = 1000,
        requests_per_day: int = 5000,
    ) -> None:
        self._base_min = min_delay
        self._base_max = max_delay
        self._current_delay = min_delay
        self._jitter = jitter

        self._hourly_limit = requests_per_hour
        self._daily_limit = requests_per_day

        self._hour_window: deque[float] = deque()
        self._day_window: deque[float] = deque()
        self._block_window: deque[float] = deque()

        self._domain_state: dict[str, dict[str, Any]] = {}

        self._response_times: deque[float] = deque(maxlen=50)
        self._baseline_response_time: float = 2.0

        self._cooldown_until: float = 0.0
        self._consecutive_blocks: int = 0

        self._recovery_state: str = "normal"
        self._recovery_start: float = 0.0
        self._recovery_target: float = min_delay
        self._recovery_step: int = 0
        self._recovery_steps_total: int = 10
        # --- Per-endpoint minimum delays (seconds) ---
        # (min, max) — random.uniform drawn each acquire
        self._endpoint_delays: dict[str, tuple[float, float]] = {
            "matches": (3.0, 8.0),
            "results": (3.0, 8.0),
            "events": (3.0, 8.0),
            "ranking": (3.0, 10.0),
            "news": (3.0, 8.0),
            "stats": (3.0, 10.0),
            "match_detail": (6.0, 15.0),
            "player_detail": (6.0, 15.0),
            "team_detail": (6.0, 15.0),
            "news_detail": (8.0, 20.0),
            "event_detail": (5.0, 15.0),
            "search": (4.0, 10.0),
            "home": (2.0, 5.0),
        }
        self._endpoint_classify_cache: dict[str, str] = {}


        self._path_state: dict[str, dict[str, Any]] = {}

        self._lock = asyncio.Lock()
        self._stats = {
            "total_requests": 0,
            "total_blocks": 0,
            "total_delays": 0.0,
            "cooldown_activations": 0,
            "recovery_cycles": 0,
        }

    async def acquire(self, url: str | None = None) -> bool:
        domain = self._extract_domain(url) if url else "default"
        now = tmod.time()
        cooldown_wait = 0.0

        async with self._lock:
            self._prune_windows(now)

            if self._hourly_limit > 0 and len(self._hour_window) >= self._hourly_limit:
                return False
            if self._daily_limit > 0 and len(self._day_window) >= self._daily_limit:
                return False

            if now < self._cooldown_until:
                cooldown_wait = self._cooldown_until - now

            self._adjust_delay(now)

            state = self._domain_state.setdefault(domain, {
                "last": 0.0, "errors": 0, "cur_delay": self._base_min,
                "response_times": deque(maxlen=20),
            })
            elapsed = now - (state["last"] or 0)
            cur_delay: float = state["cur_delay"] or self._base_min

            path_delay = self._get_path_delay(url)
            effective_delay = max(cur_delay, path_delay)

            wait = max(0.0, effective_delay - elapsed)

            if self._jitter and wait > 0:
                spread = effective_delay * 0.2
                wait = max(0.0, wait + random.gauss(0, spread))

            state["last"] = tmod.time()
            self._hour_window.append(now)
            self._day_window.append(now)
            self._stats["total_requests"] += 1

        if cooldown_wait > 0:
            await asyncio.sleep(cooldown_wait)

        if wait > 0:
            await asyncio.sleep(wait)
            self._stats["total_delays"] += wait

        return True

    async def report_error(self, url: str | None = None) -> None:
        async with self._lock:
            domain = self._extract_domain(url) if url else "default"
            state = self._domain_state.setdefault(domain, {
                "last": 0.0, "errors": 0, "cur_delay": self._base_min,
                "response_times": deque(maxlen=20),
            })
            state["errors"] = (state["errors"] or 0) + 1
            self._consecutive_blocks += 1

            factor = min(2.0 ** (state["errors"] or 0), 8.0)
            state["cur_delay"] = self._base_min * factor

            self._block_window.append(tmod.time())
            self._stats["total_blocks"] += 1

            if self._consecutive_blocks >= 3:
                cooldown_duration = min(30.0 * (2 ** (self._consecutive_blocks - 3)), 300.0)
                self._cooldown_until = tmod.time() + cooldown_duration
                self._stats["cooldown_activations"] += 1

            self._update_path_state(url, blocked=True)

            self._recovery_state = "blocked"
            self._recovery_start = 0

            total = max(len(self._hour_window), 1)
            block_rate = len(self._block_window) / total
            if block_rate > 0.05:
                self._current_delay = min(
                    self._base_max,
                    self._current_delay * (1.5 if block_rate <= 0.15 else 3.0),
                )

    async def report_success(self, url: str | None = None, response_time: float = 0.0) -> None:
        async with self._lock:
            domain = self._extract_domain(url) if url else "default"
            state = self._domain_state.setdefault(domain, {
                "last": 0.0, "errors": 0, "cur_delay": self._base_min,
                "response_times": deque(maxlen=20),
            })

            if response_time > 0:
                self._response_times.append(response_time)
                if isinstance(state.get("response_times"), deque):
                    state["response_times"].append(response_time)
                self._update_baseline_response_time()

            self._consecutive_blocks = max(0, self._consecutive_blocks - 1)

            if state["errors"] and state["errors"] > 0:
                state["errors"] = max(0, (state["errors"] or 0) - 1)
                if state["errors"] == 0:
                    if self._recovery_state != "recovering":
                        self._recovery_state = "recovering"
                        self._recovery_start = tmod.time()
                        self._recovery_target = self._base_min
                        self._recovery_step = 0
                        self._stats["recovery_cycles"] += 1

            self._update_path_state(url, blocked=False)

    def _update_baseline_response_time(self) -> None:
        if len(self._response_times) < 5:
            return
        sorted_times = sorted(self._response_times)
        trim = len(sorted_times) // 4
        if trim > 0:
            trimmed = sorted_times[trim:-trim]
        else:
            trimmed = sorted_times
        if trimmed:
            self._baseline_response_time = sum(trimmed) / len(trimmed)

    def _adjust_delay(self, now: float) -> None:
        total_recent = len(self._hour_window) or 1
        blocks_recent = len(self._block_window)
        block_rate = blocks_recent / total_recent

        if block_rate > 0.15:
            self._current_delay = min(
                self._base_max,
                self._current_delay * 3.0,
            )
        elif block_rate > 0.05:
            self._current_delay = min(
                self._base_max,
                self._current_delay * 1.5,
            )
        elif block_rate == 0 and self._current_delay > self._base_min:
            self._apply_recovery(now)

        self._adjust_for_response_time()

        self._predictive_adjust(now)

    def _apply_recovery(self, now: float) -> None:
        if self._recovery_state == "recovering":
            elapsed = now - self._recovery_start
            step_duration = 30.0
            expected_step = int(elapsed / step_duration)

            if expected_step > self._recovery_step:
                self._recovery_step = min(expected_step, self._recovery_steps_total)
                progress = self._recovery_step / self._recovery_steps_total
                eased = 1 - (1 - progress) ** 2
                self._current_delay = self._current_delay - (
                    self._current_delay - self._recovery_target
                ) * eased * 0.15
                self._current_delay = max(self._base_min, self._current_delay)

                if self._recovery_step >= self._recovery_steps_total:
                    self._current_delay = self._base_min
                    self._recovery_state = "normal"
        elif self._recovery_state == "normal":
            self._current_delay = max(
                self._base_min,
                self._current_delay * 0.97,
            )

    def _adjust_for_response_time(self) -> None:
        if len(self._response_times) < 5:
            return

        recent = list(self._response_times)[-10:]
        avg_recent = sum(recent) / len(recent)

        if avg_recent > self._baseline_response_time * 2.0:
            self._current_delay = min(
                self._base_max,
                self._current_delay * 1.2,
            )
        elif avg_recent > self._baseline_response_time * 1.5:
            self._current_delay = min(
                self._base_max,
                self._current_delay * 1.05,
            )

    def _predictive_adjust(self, now: float) -> None:
        if len(self._block_window) < 3:
            return

        recent_blocks = [t for t in self._block_window if now - t < 1800]
        if len(recent_blocks) < 2:
            return

        intervals = []
        for i in range(1, len(recent_blocks)):
            intervals.append(recent_blocks[i] - recent_blocks[i - 1])

        if not intervals:
            return

        avg_interval = sum(intervals) / len(intervals)
        if avg_interval < 60:
            self._current_delay = min(
                self._base_max,
                self._current_delay * 1.3,
            )
        elif avg_interval < 120:
            self._current_delay = min(
                self._base_max,
                self._current_delay * 1.1,
            )

    def _classify_endpoint(self, url: str | None = None) -> str:
        if not url:
            return "home"
        cached = self._endpoint_classify_cache.get(url)
        if cached:
            return cached
        try:
            from urllib.parse import urlparse
            path = urlparse(url).path.lower()
        except Exception:
            return "home"
        if "/search" in path:
            cat = "search"
        elif "/matches/" in path and path.count("/") > 3:
            cat = "match_detail"
        elif "/matches" in path:
            cat = "matches"
        elif "/results/" in path and path.count("/") > 3:
            cat = "match_detail"
        elif "/results" in path:
            cat = "results"
        elif "/ranking" in path:
            cat = "ranking"
        elif "/team/" in path:
            cat = "team_detail"
        elif "/player/" in path:
            cat = "player_detail"
        elif "/news/" in path and path.count("/") > 3:
            cat = "news_detail"
        elif "/news" in path:
            cat = "news"
        elif "/events/" in path and path.count("/") > 3:
            cat = "event_detail"
        elif "/events" in path:
            cat = "events"
        elif "/stats" in path:
            cat = "stats"
        else:
            cat = "home"
        if len(self._endpoint_classify_cache) > 2000:
            self._endpoint_classify_cache.clear()
        self._endpoint_classify_cache[url] = cat
        return cat

    def _get_endpoint_delay(self, url: str | None = None) -> float:
        cat = self._classify_endpoint(url)
        delay_range = self._endpoint_delays.get(cat)
        if delay_range:
            return random.uniform(delay_range[0], delay_range[1])
        return 0.0

    def _get_path_delay(self, url: str | None = None) -> float:
        if not url:
            return self._get_endpoint_delay(None)
        from urllib.parse import urlparse
        path = urlparse(url).path
        ps = self._path_state.get(path)
        endpoint_delay = self._get_endpoint_delay(url)
        if not ps:
            return endpoint_delay
        if ps.get("blocked_recently"):
            return max(endpoint_delay, self._base_min * 2.0)
        return endpoint_delay

    def _update_path_state(self, url: str | None, blocked: bool) -> None:
        if not url:
            return
        from urllib.parse import urlparse
        path = urlparse(url).path
        ps = self._path_state.setdefault(path, {
            "errors": 0, "successes": 0, "blocked_recently": False, "last_block": 0.0,
        })
        if blocked:
            ps["errors"] = ps.get("errors", 0) + 1
            ps["blocked_recently"] = True
            ps["last_block"] = tmod.time()
        else:
            ps["successes"] = ps.get("successes", 0) + 1
            if tmod.time() - ps.get("last_block", 0) > 300:
                ps["blocked_recently"] = False

        if len(self._path_state) > 500:
            cutoff = tmod.time() - 3600
            self._path_state = {
                k: v for k, v in self._path_state.items()
                if v.get("last_block", 0) > cutoff or v.get("successes", 0) > 0
            }

    def _extract_domain(self, url: str) -> str:
        from urllib.parse import urlparse
        return urlparse(url).netloc or "default"

    def _prune_windows(self, now: float) -> None:
        cutoff_hour = now - 3600
        cutoff_day = now - 86400
        cutoff_block = now - 3600

        while self._hour_window and self._hour_window[0] < cutoff_hour:
            self._hour_window.popleft()
        while self._day_window and self._day_window[0] < cutoff_day:
            self._day_window.popleft()
        while self._block_window and self._block_window[0] < cutoff_block:
            self._block_window.popleft()

    def get_stats(self) -> dict[str, Any]:
        total_recent = max(len(self._hour_window), 1)
        return {
            "current_delay": round(self._current_delay, 2),
            "base_min": self._base_min,
            "base_max": self._base_max,
            "hour_requests": len(self._hour_window),
            "hour_blocks": len(self._block_window),
            "block_rate": round(len(self._block_window) / total_recent, 4),
            "total_requests": self._stats["total_requests"],
            "total_blocks": self._stats["total_blocks"],
            "total_delay_time": round(self._stats["total_delays"], 1),
            "hourly_limit": self._hourly_limit,
            "daily_limit": self._daily_limit,
            "recovery_state": self._recovery_state,
            "recovery_step": f"{self._recovery_step}/{self._recovery_steps_total}",
            "consecutive_blocks": self._consecutive_blocks,
            "cooldown_active": tmod.time() < self._cooldown_until,
            "baseline_response_time": round(self._baseline_response_time, 2),
            "path_states": len(self._path_state),
            "cooldown_activations": self._stats["cooldown_activations"],
        }
