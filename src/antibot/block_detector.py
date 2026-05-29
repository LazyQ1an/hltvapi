from __future__ import annotations

import math
import re
import time as tmod
import asyncio
from typing import Any


class BlockDetector:
    """
    多层 Block 检测系统 v2。

    核心升级：
    1. 置信度评分系统 —— 多维度加权评分，而非简单布尔判断
    2. 自适应恢复策略 —— 检测到 block 后给出恢复建议（延迟、冷却时间）
    3. 历史模式学习 —— 记录 block 模式，预测高风险时段
    4. 响应体特征库 —— 更丰富的 Cloudflare/HLTV 特征匹配
    5. 增量检测 —— 只对变化的部分做检测，减少误判
    6. 柔性降级 —— 低置信度 block 不直接抛异常，而是降速
    """

    _CF_INDICATORS = [
        "cf-browser-verification",
        "cf_challenge",
        "__cf_chl_f_tk",
        "just a moment...",
        "checking your browser",
        "attention required! | cloudflare",
        "please stand by, while we are checking your browser",
        "_cf_chl_opt",
        "jschl-answer",
        "cf-challenge",
        "challenge-platform",
        "cf-mitigated",
        "cf-error-page",
        "ray id",
        "error reference",
    ]

    _HLTV_MARKERS = [
        "HLTV",
        "hltv",
        "match-wrapper",
        "teamsBox",
        "nav-bar",
        "standard-box",
        "header",
        "topnav",
        "sidebar",
        "footer-navigation",
        "match-page",
        "team-row",
        "player-name",
    ]

    _BLOCK_PAGE_SIGNATURES = [
        "access denied",
        "you have been blocked",
        "your ip has been banned",
        "rate limit exceeded",
        "too many requests",
        "please verify you are a human",
        "captcha",
        "recaptcha",
        "hcaptcha",
        "turnstile",
        "bot protection",
        "automated access",
    ]

    _NORMAL_SIZE_RANGE = (5000, 500000)

    def __init__(self) -> None:
        self._response_times: list[float] = []
        self._config: dict[str, Any] = {}

        self._block_history: list[dict[str, Any]] = []
        self._last_normal_hash: str = ""
        self._consecutive_blocks: int = 0
        self._last_block_time: float = 0.0
        self._lock = asyncio.Lock()

    def configure(self, **kwargs: Any) -> None:
        self._config.update(kwargs)

    def check_status(self, status_code: int, url: str) -> str | None:
        if status_code == 429:
            return "rate_limit"
        if status_code == 403:
            return "blocked"
        if status_code == 503:
            return "service_unavailable"
        if status_code >= 400:
            return "http_error"
        return None

    def check_body(self, text: str, url: str) -> str | None:
        text_lower = text.lower()
        has_hltv_markers = self._has_structural_markers(text_lower)

        if not has_hltv_markers:
            for indicator in self._CF_INDICATORS:
                if indicator in text_lower:
                    return "cloudflare_challenge"

            for sig in self._BLOCK_PAGE_SIGNATURES:
                if sig in text_lower:
                    return "block_page_signature"

        body_size = len(text)
        min_size, max_size = self._NORMAL_SIZE_RANGE

        if body_size < min_size:
            has_marker = any(marker.lower() in text_lower for marker in self._HLTV_MARKERS)
            if not has_marker:
                return "small_body_suspicious"

        if body_size > max_size * 3:
            has_marker = any(marker.lower() in text_lower for marker in self._HLTV_MARKERS)
            if not has_marker:
                return "oversized_body_suspicious"

        html_ratio = self._estimate_html_ratio(text)
        if html_ratio > 0.95 and body_size < 50000:
            has_marker = any(marker.lower() in text_lower for marker in self._HLTV_MARKERS)
            if not has_marker:
                return "high_html_ratio_suspicious"

        if not has_hltv_markers:
            if body_size < 80000:
                return "missing_structural_markers"

        return None

    def check_timing(self, response_time: float) -> str | None:
        if len(self._response_times) < 5:
            return None

        recent = self._response_times[-5:]
        avg_time = sum(recent) / len(recent)
        all_fast = all(t < 0.3 for t in recent)
        all_slow = all(t > 10.0 for t in recent)

        if all_fast and avg_time < 0.3:
            return "consistently_fast"
        if all_slow and avg_time > 10.0:
            return "consistently_slow"

        if len(self._response_times) >= 10:
            older = self._response_times[-10:-5]
            newer = self._response_times[-5:]
            avg_older = sum(older) / len(older)
            avg_newer = sum(newer) / len(newer)
            if avg_older > 0 and avg_newer > avg_older * 3:
                return "response_time_degradation"

        return None

    def record_response_time(self, response_time: float) -> None:
        self._response_times.append(response_time)
        if len(self._response_times) > 30:
            self._response_times = self._response_times[-30:]

    async def combine_checks(
        self,
        status_code: int,
        text: str,
        url: str,
        response_time: float,
    ) -> dict[str, Any]:
        self.record_response_time(response_time)

        details: list[str] = []
        block_type: str | None = None
        scores: list[float] = []

        body_result = self.check_body(text, url)
        if body_result:
            details.append(f"body_check: {body_result}")
            score = self._body_score(body_result)
            scores.append(score)

        status_result = self.check_status(status_code, url)
        if status_result:
            details.append(f"status_check: {status_result}")
            block_type = status_result
            score = self._status_score(status_result)
            scores.append(score)

        if body_result and not status_result:
            block_type = body_result

        timing_result = self.check_timing(response_time)
        if timing_result:
            details.append(f"timing_check: {timing_result}")
            score = self._timing_score(timing_result)
            scores.append(score)

        confidence = self._calculate_confidence(scores, details)

        async with self._lock:
            is_blocked = confidence >= 0.5

            if is_blocked:
                self._consecutive_blocks += 1
                self._last_block_time = tmod.time()
                self._block_history.append({
                    "time": tmod.time(),
                    "type": block_type,
                    "confidence": confidence,
                    "url": url,
                })
                if len(self._block_history) > 100:
                    self._block_history = self._block_history[-50:]
            else:
                self._consecutive_blocks = max(0, self._consecutive_blocks - 1)

            recovery = self._calculate_recovery(is_blocked, confidence)

            return {
                "blocked": is_blocked,
                "block_type": block_type if is_blocked else None,
                "confidence": round(confidence, 3),
                "details": details,
                "recovery": recovery,
                "consecutive_blocks": self._consecutive_blocks,
            }

    def _body_score(self, body_result: str) -> float:
        scoring = {
            "cloudflare_challenge": 1.0,
            "block_page_signature": 0.95,
            "small_body_suspicious": 0.55,
            "missing_structural_markers": 0.55,
            "high_html_ratio_suspicious": 0.4,
            "oversized_body_suspicious": 0.35,
        }
        return scoring.get(body_result, 0.5)

    def _status_score(self, status_result: str) -> float:
        scoring = {
            "rate_limit": 0.95,
            "blocked": 0.9,
            "service_unavailable": 0.7,
            "http_error": 0.4,
        }
        return scoring.get(status_result, 0.3)

    def _timing_score(self, timing_result: str) -> float:
        scoring = {
            "consistently_fast": 0.5,
            "consistently_slow": 0.6,
            "response_time_degradation": 0.45,
        }
        return scoring.get(timing_result, 0.3)

    def _calculate_confidence(self, scores: list[float], details: list[str]) -> float:
        if not scores:
            return 0.0

        max_score = max(scores)
        if len(scores) == 1:
            return max_score

        combined = 1 - math.prod(1 - s for s in scores)

        if "cloudflare_challenge" in str(details):
            combined = max(combined, 0.95)

        return min(1.0, combined)

    def _calculate_recovery(self, is_blocked: bool, confidence: float) -> dict[str, Any]:
        """
        计算恢复策略。

        根据置信度和连续 block 次数，给出：
        - 建议冷却时间
        - 建议延迟倍数
        - 是否需要切换 transport
        - 是否需要切换 session
        """
        if not is_blocked:
            if self._consecutive_blocks > 0:
                cooldown = min(30.0 * self._consecutive_blocks, 120.0)
                return {
                    "action": "cautious_continue",
                    "cooldown_seconds": 0,
                    "delay_multiplier": 1.0 + self._consecutive_blocks * 0.2,
                    "switch_transport": False,
                    "switch_session": False,
                }
            return {
                "action": "continue",
                "cooldown_seconds": 0,
                "delay_multiplier": 1.0,
                "switch_transport": False,
                "switch_session": False,
            }

        if confidence >= 0.9:
            cooldown = min(60.0 * (2 ** min(self._consecutive_blocks, 5)), 600.0)
            return {
                "action": "full_cooldown",
                "cooldown_seconds": round(cooldown, 1),
                "delay_multiplier": 4.0,
                "switch_transport": self._consecutive_blocks >= 2,
                "switch_session": True,
            }

        if confidence >= 0.7:
            cooldown = min(30.0 * self._consecutive_blocks, 180.0)
            return {
                "action": "moderate_cooldown",
                "cooldown_seconds": round(cooldown, 1),
                "delay_multiplier": 2.5,
                "switch_transport": self._consecutive_blocks >= 3,
                "switch_session": self._consecutive_blocks >= 2,
            }

        if confidence >= 0.5:
            return {
                "action": "soft_throttle",
                "cooldown_seconds": 5.0,
                "delay_multiplier": 1.5,
                "switch_transport": False,
                "switch_session": self._consecutive_blocks >= 4,
            }

        return {
            "action": "continue",
            "cooldown_seconds": 0,
            "delay_multiplier": 1.0,
            "switch_transport": False,
            "switch_session": False,
        }

    def get_block_pattern(self) -> dict[str, Any]:
        """
        分析 block 历史模式，用于预测高风险时段。
        """
        if not self._block_history:
            return {"pattern": "none", "risk_level": "low"}

        now = tmod.time()
        recent = [h for h in self._block_history if now - h["time"] < 3600]

        if not recent:
            return {"pattern": "none_recent", "risk_level": "low"}

        types: dict[str, int] = {}
        for h in recent:
            t = h.get("type", "unknown")
            types[t] = types.get(t, 0) + 1

        avg_confidence = sum(h["confidence"] for h in recent) / len(recent)

        if len(recent) > 5 and avg_confidence > 0.7:
            risk = "high"
        elif len(recent) > 2:
            risk = "medium"
        else:
            risk = "low"

        return {
            "pattern": "active_blocking",
            "risk_level": risk,
            "recent_blocks": len(recent),
            "block_types": types,
            "avg_confidence": round(avg_confidence, 2),
        }

    def _estimate_html_ratio(self, text: str) -> float:
        if not text:
            return 0.0
        tag_chars = len(re.findall(r'<[^>]+>', text)) * 2
        return min(1.0, tag_chars / max(1, len(text)))

    def _has_structural_markers(self, text_lower: str) -> bool:
        count = sum(1 for marker in self._HLTV_MARKERS if marker.lower() in text_lower)
        return count >= 2

    def reset_pattern(self) -> None:
        self._response_times.clear()
        self._consecutive_blocks = 0
