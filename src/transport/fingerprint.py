from __future__ import annotations

import random


class TLSFingerprintManager:
    """
    TLS 指纹管理。

    维护一组可用的 TLS fingerprint 版本。
    每个 session 关联一个版本，不频繁切换以免产生异常特征。
    """

    # curl_cffi 支持的 impersonate 版本
    _SUPPORTED_VERSIONS = [
        "chrome124",
        "chrome131",
        "chrome136",
        "edge101",
        "safari18_0",
        "firefox133",
        "firefox135",
    ]

    def __init__(self) -> None:
        self._version_usage: dict[str, int] = {v: 0 for v in self._SUPPORTED_VERSIONS}

    def assign(self) -> str:
        """为新的 session 分配一个 TLS 版本。使用最少使用的版本以保持负载均衡。"""
        min_used = min(self._version_usage.values())
        candidates = [v for v, c in self._version_usage.items() if c == min_used]
        chosen = random.choice(candidates)
        self._version_usage[chosen] += 1
        return chosen

    def rotate(self, current: str) -> str:
        """轮换到一个不同的版本。"""
        alternatives = [v for v in self._SUPPORTED_VERSIONS if v != current]
        chosen = random.choice(alternatives)
        self._version_usage[chosen] = self._version_usage.get(chosen, 0) + 1
        return chosen

    def get_usage_stats(self) -> dict[str, int]:
        return dict(self._version_usage)
