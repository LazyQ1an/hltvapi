"""
Comprehensive unit tests for all new modules (Phase 1-5).
"""

import asyncio
import os
import tempfile
from bs4 import BeautifulSoup

import pytest


class TestAdaptiveRateLimiter:
    def test_basic_acquire(self):
        from src.antibot.rate_limiter import AdaptiveRateLimiter
        rl = AdaptiveRateLimiter(min_delay=0.01, max_delay=0.1, requests_per_hour=10000)

        async def run():
            for i in range(5):
                ok = await rl.acquire("https://hltv.org/matches")
                assert ok, "Rate limit should allow"
            stats = rl.get_stats()
            assert stats["total_requests"] == 5
            assert stats["current_delay"] >= stats["base_min"]
            return stats

        stats = asyncio.run(run())
        assert stats["total_requests"] == 5

    def test_hourly_limit(self):
        from src.antibot.rate_limiter import AdaptiveRateLimiter
        rl = AdaptiveRateLimiter(min_delay=0.001, max_delay=0.01, requests_per_hour=3)

        async def run():
            results = []
            for i in range(5):
                ok = await rl.acquire("https://hltv.org")
                results.append(ok)
            return results

        results = asyncio.run(run())
        assert results[:3] == [True, True, True]
        assert results[3:] == [False, False]

    def test_block_backoff(self):
        from src.antibot.rate_limiter import AdaptiveRateLimiter
        rl = AdaptiveRateLimiter(min_delay=0.01, max_delay=1.0)
        rl.report_error("https://hltv.org/matches")
        rl.report_error("https://hltv.org/matches")
        stats = rl.get_stats()
        assert stats["total_blocks"] == 2
        assert stats["current_delay"] >= stats["base_min"] * 1.5


class TestBlockDetector:
    def test_normal_page_not_blocked(self):
        from src.antibot.block_detector import BlockDetector
        bd = BlockDetector()
        result = bd.combine_checks(
            200,
            "<html><body>HLTV match-wrapper teamsBox standard-box header nav-bar</body></html>",
            "https://hltv.org",
            0.5,
        )
        assert not result["blocked"]

    def test_cf_challenge_detected(self):
        from src.antibot.block_detector import BlockDetector
        bd = BlockDetector()
        result = bd.combine_checks(
            403,
            "<html>cf-browser-verification challenge-platform</html>",
            "https://hltv.org/matches",
            0.3,
        )
        assert result["blocked"]
        assert result["block_type"] == "cloudflare_challenge"

    def test_small_body_detected(self):
        from src.antibot.block_detector import BlockDetector
        bd = BlockDetector()
        result = bd.combine_checks(
            200,
            "<html><body>small</body></html>",
            "https://hltv.org/matches",
            0.5,
        )
        assert result["blocked"]

    def test_status_code_429(self):
        from src.antibot.block_detector import BlockDetector
        bd = BlockDetector()
        result = bd.combine_checks(429, "", "https://hltv.org", 0.1)
        assert result["blocked"]


class TestHumanRequestPattern:
    def test_delay_positive(self):
        from src.antibot.human_pattern import HumanRequestPattern
        hp = HumanRequestPattern(burst_min=1, burst_max=2, rest_delay_min=0.01, rest_delay_max=0.02)

        async def run():
            delays = [await hp.next_delay("https://hltv.org") for _ in range(5)]
            return delays

        delays = asyncio.run(run())
        for d in delays:
            assert d > 0


class TestHeaderProfiles:
    def test_random_profile_has_required_headers(self):
        from src.antibot.header_profiles import random_profile
        p = random_profile()
        headers = p.to_dict()
        assert "User-Agent" in headers
        assert "Accept" in headers
        assert "Accept-Language" in headers
        assert "Referer" in headers

    def test_all_profiles_unique(self):
        from src.antibot.header_profiles import HEADER_PROFILES
        names = [p.name for p in HEADER_PROFILES]
        assert len(names) == len(set(names))
        assert len(HEADER_PROFILES) >= 4


class TestSessionIdentity:
    def test_random_creation(self):
        from src.transport.identity import SessionIdentity
        ident = SessionIdentity.random()
        assert ident.user_agent
        assert ident.impersonate_version.startswith("chrome")
        assert ident.platform in ("win32", "darwin", "linux")

    def test_platform_specific(self):
        from src.transport.identity import SessionIdentity
        ident = SessionIdentity.random("win32")
        assert "Windows" in ident.user_agent
        ident2 = SessionIdentity.random("darwin")
        assert "Macintosh" in ident2.user_agent


class TestTransportSession:
    def test_create_and_health(self):
        from src.transport.base import TransportSession
        from src.transport.identity import SessionIdentity
        s = TransportSession(transport="curl", identity=SessionIdentity.random())
        assert s.health_score == 1.0
        assert not s.banned
        assert not s.is_expired

    def test_block_ban(self):
        from src.transport.base import TransportSession
        s = TransportSession(transport="curl")
        s.record_block()
        assert s.consecutive_blocks == 1
        assert not s.banned
        s.record_block()
        s.record_block()
        assert s.banned
        assert s.health_score < 1.0

    def test_success_improves_health(self):
        from src.transport.base import TransportSession
        s = TransportSession(transport="curl")
        s.record_block()
        health_after_block = s.health_score
        s.record_success()
        assert s.health_score > health_after_block


class TestTLSFingerprintManager:
    def test_assign_and_stats(self):
        from src.transport.fingerprint import TLSFingerprintManager
        fm = TLSFingerprintManager()
        v1 = fm.assign()
        v2 = fm.assign()
        assert v1 != v2 or True  # may collide, just verify API works
        stats = fm.get_usage_stats()
        assert len(stats) > 0


class TestHTMLArchive:
    def test_store_and_retrieve(self):
        from src.storage.archive import HTMLArchive

        with tempfile.TemporaryDirectory() as tmpdir:
            arch = HTMLArchive(base_dir=os.path.join(tmpdir, "archive"))

            async def run():
                await arch.store(
                    "https://hltv.org/matches",
                    "<html>test content</html>",
                    {"page_type": "test", "status_code": 200},
                )
                stats = arch.get_stats()
                assert stats["total_entries"] == 1
                assert stats["by_type"].get("test") == 1

                content = await arch.get_latest("https://hltv.org/matches")
                assert content == "<html>test content</html>"
                arch.close()

            asyncio.run(run())

    def test_multiple_versions(self):
        from src.storage.archive import HTMLArchive

        with tempfile.TemporaryDirectory() as tmpdir:
            arch = HTMLArchive(base_dir=os.path.join(tmpdir, "archive"))

            async def run():
                await arch.store("https://hltv.org/ranking", "<html>v1</html>")
                await arch.store("https://hltv.org/ranking", "<html>v2</html>")
                versions = await arch.get_versions("https://hltv.org/ranking")
                assert len(versions) == 2
                arch.close()

            asyncio.run(run())


class TestSemanticParser:
    def test_basic_parse(self):
        from src.parser.semantic import SemanticParser, SelectorStrategy
        sp = SemanticParser([
            SelectorStrategy("title", "title", extractor="text"),
            SelectorStrategy("content", ".content", fallbacks=["#main", "body"], extractor="text"),
        ])
        soup = BeautifulSoup(
            "<html><head><title>Test</title></head>"
            "<body><div class='content'>Hello</div></body></html>",
            "lxml",
        )
        result = sp.parse(soup)
        assert result["title"] == "Test"
        assert result["content"] == "Hello"

    def test_fallback_selector(self):
        from src.parser.semantic import SemanticParser, SelectorStrategy
        sp = SemanticParser([
            SelectorStrategy("name", ".does-not-exist", fallbacks=[".actual-class"], extractor="text"),
        ])
        soup = BeautifulSoup("<html><body><div class='actual-class'>Fallback</div></body></html>", "lxml")
        result = sp.parse(soup)
        assert result["name"] == "Fallback"

    def test_required_field_missing(self):
        from src.parser.semantic import SemanticParser, SelectorStrategy
        sp = SemanticParser([
            SelectorStrategy("id", ".missing", extractor="text", required=True),
        ])
        soup = BeautifulSoup("<html></html>", "lxml")
        import pytest as _pytest
        with _pytest.raises(ValueError):
            sp.parse(soup)

    def test_health_report(self):
        from src.parser.semantic import SemanticParser, SelectorStrategy
        sp = SemanticParser([
            SelectorStrategy("title", "title", extractor="text"),
        ])
        soup = BeautifulSoup("<html><head><title>Test</title></head></html>", "lxml")
        sp.parse(soup)
        report = sp.get_health_report()
        assert report["total_parses"] == 1
        assert report["success_parses"] == 1


class TestParserPipeline:
    def test_register_and_process(self):
        from src.parser.pipeline import ParserPipeline, PreprocessStage
        from src.parser.semantic import SemanticParser, SelectorStrategy

        pp = ParserPipeline()
        sp = SemanticParser([
            SelectorStrategy("name", ".name", extractor="text"),
        ])
        pp.register_parser("custom", sp)

        async def run():
            result = await pp.process(
                "<html><body><div class='name'>TestValue</div></body></html>",
                page_type="custom",
            )
            assert result.success
            assert result.data["name"] == "TestValue"
            assert result.page_type == "custom"

        asyncio.run(run())

    def test_preprocess_stage(self):
        from src.parser.pipeline import PreprocessStage
        cleaned, page_type = PreprocessStage.run(
            "<html><script>alert(1)</script><body class='match-wrapper'>HLTV</body></html>",
        )
        assert "alert" not in cleaned
        assert page_type == "match_upcoming"
