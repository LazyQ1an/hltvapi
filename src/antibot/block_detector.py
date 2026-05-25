from __future__ import annotations

import re
from typing import Any


class BlockDetector:
    """
    多层 Block 检测系统。

    Level 1: HTTP 状态码
    Level 2: 关键词匹配（Cloudflare challenge 指纹）
    Level 3: 响应体大小 + 内容熵分析
    Level 4: DOM 结构指纹（标记 HLTV 特有元素的存在）
    Level 5: 响应时间模式检测（全局突然变快/变慢）

    与旧版区别：
    - 旧版: _check_blocked + _check_status 嵌入式方法
    - 新版: 独立模块 + Level 3/4/5 增强检测 + 可扩展匹配模式
    """

    # Level 2: Cloudflare challenge 关键词
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
    ]

    # Level 4: HLTV 正常页面必须存在的 DOM marker（CSS class 或 id）
    _HLTV_MARKERS = [
        "HLTV",
        "hltv",
        "match-wrapper",
        "teamsBox",
        "nav-bar",
        "standard-box",
        "header",
    ]

    def __init__(self) -> None:
        self._consecutive_fast_responses = 0
        self._consecutive_slow_responses = 0
        self._last_response_times: list[float] = []
        self._config: dict[str, Any] = {}

    def configure(self, **kwargs: Any) -> None:
        self._config.update(kwargs)

    def check_status(self, status_code: int, url: str) -> str | None:
        """
        检查 HTTP 状态码，返回 block 类型或 None。

        Returns:
            "rate_limit" | "blocked" | None
        """
        if status_code == 429:
            return "rate_limit"
        if status_code == 403:
            return "blocked"
        if status_code >= 400:
            return "http_error"
        return None

    def check_body(self, text: str, url: str) -> str | None:
        """
        检查响应体，返回 block 类型或 None。

        Level 2 + Level 3 + Level 4 组合检测。
        """
        text_lower = text.lower()

        # Level 2: 关键词检测
        for indicator in self._CF_INDICATORS:
            if indicator in text_lower:
                return "cloudflare_challenge"

        # Level 3: 小响应检测（<20KB 且无 HLTV marker）
        if len(text) < 20000:
            has_marker = any(marker.lower() in text_lower for marker in self._HLTV_MARKERS)
            if not has_marker:
                return "small_body_suspicious"

        # Level 3+: HTML 内容比例异常（block 页面通常 HTML > 90%）
        # selectolax/bs4 不可用时，用粗略 HTML 标签占比估算
        html_ratio = self._estimate_html_ratio(text)
        if html_ratio > 0.95 and len(text) < 50000:
            has_marker = any(marker.lower() in text_lower for marker in self._HLTV_MARKERS)
            if not has_marker:
                return "high_html_ratio_suspicious"

        # Level 4: DOM 结构指纹
        if not self._has_structural_markers(text_lower):
            if len(text) < 80000:
                return "missing_structural_markers"

        return None

    def check_timing(self, response_time: float) -> str | None:
        """
        Level 5: 响应时间模式检测。

        正常 HLTV 页面响应时间通常在 500ms-5s 之间。
        如果突然所有请求都 < 300ms 或 > 10s，可能是异常。

        Returns:
            "suspicious_timing" | None
        """
        self._last_response_times.append(response_time)
        if len(self._last_response_times) > 20:
            self._last_response_times.pop(0)

        if len(self._last_response_times) < 5:
            return None

        avg_time = sum(self._last_response_times) / len(self._last_response_times)
        all_fast = all(t < 0.3 for t in self._last_response_times[-5:])
        all_slow = all(t > 10.0 for t in self._last_response_times[-5:])

        if all_fast and avg_time < 0.3:
            return "consistently_fast"
        if all_slow and avg_time > 10.0:
            return "consistently_slow"

        return None

    def combine_checks(
        self,
        status_code: int,
        text: str,
        url: str,
        response_time: float,
    ) -> dict[str, Any]:
        """
        综合所有检测，返回判决结果。

        Returns:
            {
                "blocked": bool,
                "block_type": str | None,
                "confidence": float,  # 0.0 - 1.0
                "details": list[str],
            }
        """
        details: list[str] = []
        block_type: str | None = None

        body_result = self.check_body(text, url)
        if body_result:
            details.append(f"body_check: {body_result}")
            block_type = body_result

        status_result = self.check_status(status_code, url)
        if status_result:
            details.append(f"status_check: {status_result}")
            block_type = block_type or status_result

        timing_result = self.check_timing(response_time)
        if timing_result:
            details.append(f"timing_check: {timing_result}")

        is_blocked = block_type is not None or len(details) >= 2

        confidence = 0.0
        if "cloudflare_challenge" in details:
            confidence = 1.0
        elif body_result:
            confidence = 0.85
        elif status_result == "blocked":
            confidence = 0.9
        elif len(details) >= 2:
            confidence = 0.7
        elif len(details) == 1:
            confidence = 0.4

        return {
            "blocked": is_blocked,
            "block_type": block_type if is_blocked else None,
            "confidence": round(confidence, 2),
            "details": details,
        }

    def _estimate_html_ratio(self, text: str) -> float:
        """粗略估算 HTML 标签占比。"""
        if not text:
            return 0.0
        tag_chars = len(re.findall(r'<[^>]+>', text)) * 2
        return min(1.0, tag_chars / max(1, len(text)))

    def _has_structural_markers(self, text_lower: str) -> bool:
        """检查是否包含 HLTV 页面应有的 DOM 结构标记。"""
        count = sum(1 for marker in self._HLTV_MARKERS if marker.lower() in text_lower)
        return count >= 2

    def reset_pattern(self) -> None:
        """重置响应时间模式检测状态。"""
        self._consecutive_fast_responses = 0
        self._consecutive_slow_responses = 0
        self._last_response_times.clear()
