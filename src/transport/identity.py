from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Literal


@dataclass
class SessionIdentity:
    """
    一个 session 的完整身份指纹。

    一个 session 从创建到退役，只使用一个 identity。
    这比每请求随机切换更真实——真实用户不会在浏览途中切换浏览器。
    """

    user_agent: str
    accept_language: str = "en-US,en;q=0.9"
    platform: Literal["win32", "darwin", "linux"] = "win32"
    viewport_width: int = 1920
    viewport_height: int = 1080
    timezone: str = "America/New_York"
    locale: str = "en-US"
    hardware_concurrency: int = 8
    device_memory: int = 8

    # TLS 指纹相关
    tls_version: str = "chrome124"

    # curl_cffi 的 impersonate 版本
    impersonate_version: str = "chrome124"

    @classmethod
    def random(cls, platform: str | None = None) -> SessionIdentity:
        """
        从模板生成随机 identity。

        Args:
            platform: 可选，指定平台类型。
        """
        if platform is None:
            platform = random.choice(["win32", "darwin", "linux"])

        if platform == "win32":
            ua = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/{}.0.0.0 Safari/537.36"
            )
            tz = random.choice(["America/New_York", "America/Chicago", "Europe/London"])
        elif platform == "darwin":
            ua = (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_3) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/{}.0.0.0 Safari/537.36"
            )
            tz = random.choice(["America/New_York", "Europe/London"])
        else:
            ua = (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/{}.0.0.0 Safari/537.36"
            )
            tz = "UTC"

        chrome_ver = random.choice(["124", "128", "130", "131", "132"])
        ua = ua.format(chrome_ver)

        viewport = random.choice([
            (1920, 1080), (1366, 768), (1440, 900), (1536, 864), (2560, 1440),
        ])
        hw_concurrency = random.choice([4, 6, 8, 12, 16])
        device_mem = random.choice([4, 8, 8, 16])
        lang = random.choice([
            "en-US,en;q=0.9",
            "en-US,en;q=0.9,fr;q=0.8",
            "en-GB,en;q=0.9,en-US;q=0.8",
            "en;q=0.9",
            "en-US,en;q=0.8,de;q=0.6",
        ])

        return cls(
            user_agent=ua,
            accept_language=lang,
            platform=platform,
            viewport_width=viewport[0],
            viewport_height=viewport[1],
            timezone=tz,
            hardware_concurrency=hw_concurrency,
            device_memory=device_mem,
            tls_version=f"chrome{chrome_ver}",
            impersonate_version=f"chrome{chrome_ver}",
        )
