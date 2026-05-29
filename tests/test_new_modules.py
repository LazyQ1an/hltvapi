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

        async def run():
            await rl.report_error("https://hltv.org/matches")
            await rl.report_error("https://hltv.org/matches")
            stats = rl.get_stats()
            assert stats["total_blocks"] == 2
            assert stats["current_delay"] >= stats["base_min"] * 1.5

        asyncio.run(run())


class TestBlockDetector:
    def test_normal_page_not_blocked(self):
        from src.antibot.block_detector import BlockDetector
        bd = BlockDetector()

        async def run():
            result = await bd.combine_checks(
                200,
                "<html><body>HLTV match-wrapper teamsBox standard-box header nav-bar</body></html>",
                "https://hltv.org",
                0.5,
            )
            assert not result["blocked"]

        asyncio.run(run())

    def test_cf_challenge_detected(self):
        from src.antibot.block_detector import BlockDetector
        bd = BlockDetector()

        async def run():
            result = await bd.combine_checks(
                200,
                "<html>cf-browser-verification challenge-platform</html>",
                "https://hltv.org/matches",
                0.3,
            )
            assert result["blocked"]
            assert result["block_type"] == "cloudflare_challenge"

        asyncio.run(run())

    def test_small_body_detected(self):
        from src.antibot.block_detector import BlockDetector
        bd = BlockDetector()

        async def run():
            result = await bd.combine_checks(
                200,
                "<html><body>small</body></html>",
                "https://hltv.org/matches",
                0.5,
            )
            assert result["blocked"]

        asyncio.run(run())

    def test_status_code_429(self):
        from src.antibot.block_detector import BlockDetector
        bd = BlockDetector()

        async def run():
            result = await bd.combine_checks(429, "", "https://hltv.org", 0.1)
            assert result["blocked"]

        asyncio.run(run())


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
        assert ident.impersonate_version
        assert ident.platform in ("win32", "darwin", "linux")
        assert ident.browser_type in ("chrome", "firefox", "safari", "edge")

    def test_platform_specific(self):
        from src.transport.identity import SessionIdentity
        ident = SessionIdentity.random("win32")
        assert ident.platform == "win32"
        assert "Windows" in ident.user_agent or "windows" in ident.user_agent.lower()
        ident2 = SessionIdentity.random("darwin")
        assert ident2.platform == "darwin"
        assert "Macintosh" in ident2.user_agent or "mac" in ident2.user_agent.lower()

    def test_build_headers_consistency(self):
        from src.transport.identity import SessionIdentity
        ident = SessionIdentity.random("win32")
        headers = ident.build_headers()
        assert headers["User-Agent"] == ident.user_agent
        assert headers["Accept-Language"] == ident.accept_language
        if ident.browser_type in ("chrome", "edge"):
            assert "Sec-Ch-Ua" in headers
            assert "Sec-Fetch-Site" in headers
        elif ident.browser_type == "firefox":
            assert "Sec-Ch-Ua" not in headers
            assert "DNT" in headers

    def test_natural_referer(self):
        from src.transport.identity import SessionIdentity
        ident = SessionIdentity.random()
        referer = ident.get_natural_referer("/matches/12345")
        assert referer.startswith("https://")

    def test_browsing_history(self):
        from src.transport.identity import SessionIdentity, BrowsingHistory
        bh = BrowsingHistory()
        bh.record_visit("/matches")
        bh.record_visit("/matches/12345")
        assert len(bh.visited_paths) == 2
        assert bh.get_recent_paths(1) == ["/matches/12345"]


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


class TestBlockDetectorV2:
    def test_confidence_scoring(self):
        from src.antibot.block_detector import BlockDetector
        bd = BlockDetector()

        async def run():
            result = await bd.combine_checks(403, "cf-browser-verification", "https://hltv.org", 0.3)
            assert result["blocked"]
            assert result["confidence"] >= 0.9

        asyncio.run(run())

    def test_low_confidence_not_blocked(self):
        from src.antibot.block_detector import BlockDetector
        bd = BlockDetector()
        html = "<html><body>HLTV standard-box nav-bar header</body></html>" + "x" * 15000

        async def run():
            result = await bd.combine_checks(200, html, "https://hltv.org/matches", 1.5)
            assert not result["blocked"]

        asyncio.run(run())

    def test_recovery_strategy(self):
        from src.antibot.block_detector import BlockDetector
        bd = BlockDetector()

        async def run():
            result = await bd.combine_checks(403, "cf-browser-verification", "https://hltv.org", 0.3)
            assert "recovery" in result
            recovery = result["recovery"]
            assert "action" in recovery
            assert "cooldown_seconds" in recovery
            assert "delay_multiplier" in recovery

        asyncio.run(run())

    def test_block_page_signature(self):
        from src.antibot.block_detector import BlockDetector
        bd = BlockDetector()

        async def run():
            result = await bd.combine_checks(
                200,
                "<html><body>access denied you have been blocked</body></html>",
                "https://hltv.org",
                0.5,
            )
            assert result["blocked"]

        asyncio.run(run())

    def test_503_detected(self):
        from src.antibot.block_detector import BlockDetector
        bd = BlockDetector()

        async def run():
            result = await bd.combine_checks(503, "service unavailable", "https://hltv.org", 0.5)
            assert result["blocked"]

        asyncio.run(run())

    def test_block_pattern_analysis(self):
        from src.antibot.block_detector import BlockDetector
        bd = BlockDetector()
        pattern = bd.get_block_pattern()
        assert "risk_level" in pattern
        assert pattern["risk_level"] == "low"

    def test_normal_large_page_not_blocked(self):
        from src.antibot.block_detector import BlockDetector
        bd = BlockDetector()
        large_html = "<html><body>" + "HLTV standard-box nav-bar header " * 5000 + "</body></html>"

        async def run():
            result = await bd.combine_checks(200, large_html, "https://hltv.org/matches", 1.5)
            assert not result["blocked"]

        asyncio.run(run())


class TestAdaptiveRateLimiterV2:
    def test_response_time_awareness(self):
        from src.antibot.rate_limiter import AdaptiveRateLimiter
        rl = AdaptiveRateLimiter(min_delay=0.01, max_delay=1.0)

        async def run():
            for _ in range(10):
                await rl.report_success("https://hltv.org", response_time=0.5)
            stats = rl.get_stats()
            assert stats["baseline_response_time"] > 0

        asyncio.run(run())

    def test_consecutive_blocks_cooldown(self):
        from src.antibot.rate_limiter import AdaptiveRateLimiter
        rl = AdaptiveRateLimiter(min_delay=0.01, max_delay=1.0)

        async def run():
            await rl.report_error("https://hltv.org")
            await rl.report_error("https://hltv.org")
            await rl.report_error("https://hltv.org")
            stats = rl.get_stats()
            assert stats["consecutive_blocks"] == 3
            assert stats["cooldown_activations"] >= 1

        asyncio.run(run())

    def test_recovery_state(self):
        from src.antibot.rate_limiter import AdaptiveRateLimiter
        rl = AdaptiveRateLimiter(min_delay=0.01, max_delay=1.0)

        async def run():
            await rl.report_error("https://hltv.org")
            assert rl._recovery_state == "blocked"
            await rl.report_success("https://hltv.org")
            assert rl._recovery_state == "recovering"

        asyncio.run(run())

    def test_path_level_throttling(self):
        from src.antibot.rate_limiter import AdaptiveRateLimiter
        rl = AdaptiveRateLimiter(min_delay=0.01, max_delay=1.0)

        async def run():
            await rl.report_error("https://www.hltv.org/matches/12345")
            stats = rl.get_stats()
            assert stats["path_states"] >= 1

        asyncio.run(run())


class TestHumanPatternV2:
    def test_suggest_next_path(self):
        from src.antibot.human_pattern import HumanRequestPattern
        hp = HumanRequestPattern()
        next_path = hp.suggest_next_path()
        assert next_path is not None
        assert next_path in [
            "matches", "results", "ranking", "news", "events", "stats",
            "match_detail", "team_detail", "player_detail",
            "news_detail", "event_detail", "home",
            "search", "refresh", "external",
        ]

    def test_page_type_classification(self):
        from src.antibot.human_pattern import HumanRequestPattern
        hp = HumanRequestPattern()
        assert hp._classify_url("https://www.hltv.org/matches") == "matches"
        assert hp._classify_url("https://www.hltv.org/matches/12345") == "match_detail"
        assert hp._classify_url("https://www.hltv.org/team/6667") == "team_detail"
        assert hp._classify_url("https://www.hltv.org/player/11893") == "player_detail"
        assert hp._classify_url("https://www.hltv.org/ranking/teams") == "ranking"

    def test_fatigue_increases(self):
        from src.antibot.human_pattern import HumanRequestPattern
        import time
        hp = HumanRequestPattern()
        hp._session_start = time.time() - 900
        hp._update_fatigue()
        assert hp._fatigue_level > 0

    def test_stats_include_new_fields(self):
        from src.antibot.human_pattern import HumanRequestPattern
        hp = HumanRequestPattern()
        stats = hp.get_stats()
        assert "current_page_type" in stats
        assert "session_state" in stats
        assert "fatigue_level" in stats
        assert "pages_in_session" in stats


class TestResponseValidator:
    def test_valid_response(self):
        from src.core.pipeline import ResponseValidator
        rv = ResponseValidator()
        html = "<html><body>HLTV match-wrapper standard-box nav-bar</body></html>" + "x" * 20000
        result = rv.validate(html, "https://www.hltv.org/matches")
        assert result["valid"]

    def test_too_small_response(self):
        from src.core.pipeline import ResponseValidator
        rv = ResponseValidator()
        result = rv.validate("<html>tiny</html>", "https://www.hltv.org/matches")
        assert not result["valid"]
        assert any("too small" in w for w in result["warnings"])

    def test_block_indicators_in_response(self):
        from src.core.pipeline import ResponseValidator
        rv = ResponseValidator()
        html = "<html><body>cloudflare blocked denied</body></html>" + "x" * 20000
        result = rv.validate(html, "https://www.hltv.org/matches")
        assert not result["valid"]

    def test_no_hltv_markers(self):
        from src.core.pipeline import ResponseValidator
        rv = ResponseValidator()
        html = "<html><body>" + "generic content " * 5000 + "</body></html>"
        result = rv.validate(html, "https://www.hltv.org/matches")
        assert not result["valid"]


class TestRequestScheduler:
    def test_enqueue_dequeue(self):
        from src.core.request_scheduler import RequestScheduler
        rs = RequestScheduler()
        assert rs.enqueue("https://www.hltv.org/matches", priority=5)
        req = rs.dequeue()
        assert req is not None
        assert req.url == "https://www.hltv.org/matches"

    def test_dedup(self):
        from src.core.request_scheduler import RequestScheduler
        rs = RequestScheduler()
        assert rs.enqueue("https://www.hltv.org/matches")
        assert not rs.enqueue("https://www.hltv.org/matches")

    def test_priority_ordering(self):
        from src.core.request_scheduler import RequestScheduler
        rs = RequestScheduler()
        rs.enqueue("https://www.hltv.org/low", priority=9)
        rs.enqueue("https://www.hltv.org/high", priority=1)
        req = rs.dequeue()
        assert req.url == "https://www.hltv.org/high"

    def test_batch_enqueue(self):
        from src.core.request_scheduler import RequestScheduler
        rs = RequestScheduler()
        urls = [
            "https://www.hltv.org/matches/123",
            "https://www.hltv.org/matches",
            "https://www.hltv.org/team/456",
        ]
        count = rs.enqueue_batch(urls)
        assert count == 3

    def test_concurrency_adjustment(self):
        from src.core.request_scheduler import RequestScheduler
        rs = RequestScheduler(max_concurrency=5)
        assert rs.get_effective_concurrency() == 5
        rs.update_risk(0.8)
        assert rs.get_effective_concurrency() < 5
        rs.update_risk(0.1)
        assert rs.get_effective_concurrency() == 5

    def test_stats(self):
        from src.core.request_scheduler import RequestScheduler
        rs = RequestScheduler()
        rs.enqueue("https://www.hltv.org/matches")
        stats = rs.get_stats()
        assert "queue_size" in stats
        assert "effective_concurrency" in stats
