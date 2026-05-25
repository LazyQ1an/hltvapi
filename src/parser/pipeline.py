"""
Parser Pipeline — 多阶段解析器流水线。

Stage 1: Preprocess — HTML 清洗、提取 JSON-LD、识别页面类型
Stage 2: Semantic Parse — 使用 SelectorStrategy 链解析
Stage 3: Validation — 校验字段完整性
Stage 4: Enrichment — 数据补全
Stage 5: Output — Pydantic model + 统计
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable

from .semantic import SemanticParser

logger = logging.getLogger("hltv.parser.pipeline")


class ParseResult:
    """解析结果。"""
    def __init__(
        self,
        data: dict[str, Any],
        page_type: str,
        success: bool = True,
        errors: list[str] | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        self.data = data
        self.page_type = page_type
        self.success = success
        self.errors = errors or []
        self.warnings = warnings or []


class PreprocessStage:
    """预处理阶段。"""

    @staticmethod
    def run(html: str) -> tuple[str, str]:
        """
        清洗 HTML + 识别页面类型。

        Returns:
            (cleaned_html, page_type)
        """
        page_type = PreprocessStage._detect_page_type(html)
        cleaned = PreprocessStage._clean_html(html)
        return cleaned, page_type

    @staticmethod
    def _detect_page_type(html: str) -> str:
        """通过 HTML 特征识别页面类型。"""
        html_lower = html.lower()

        if "match-meta-live" in html_lower:
            return "match_live"
        if "match-wrapper" in html_lower:
            return "match_upcoming"
        if "result-con" in html_lower:
            return "match_result"
        if "teamsBox" in html_lower:
            return "match_detail"
        if "ranked-team" in html_lower or "ranking-header" in html_lower:
            return "team_ranking"
        if "player-stat" in html_lower or "stats-top" in html_lower:
            return "player_stats"
        if "news-standard" in html_lower or "newsgroup" in html_lower:
            return "news"
        if "event-world" in html_lower:
            return "event"
        return "unknown"

    @staticmethod
    def _clean_html(html: str) -> str:
        """基础 HTML 清洗。"""
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
        html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
        return html


class ValidationStage:
    """校验阶段。"""

    @staticmethod
    def run(data: dict, rules: dict[str, Callable] | None = None) -> list[str]:
        errors = []

        # ID 校验
        for id_field in [k for k in data if k.endswith("_id")]:
            val = data.get(id_field)
            if val is not None and (not isinstance(val, int) or val <= 0):
                errors.append(f"{id_field}: invalid value {val}")

        # 比分校验
        for score_field in [k for k in data if "score" in k.lower()]:
            val = data.get(score_field)
            if val is not None and (not isinstance(val, (int, float)) or val < 0 or val > 50):
                errors.append(f"{score_field}: out of range {val}")

        # 自定义校验规则
        if rules:
            for field, validator in rules.items():
                if field in data:
                    try:
                        if not validator(data[field]):
                            errors.append(f"{field}: custom validation failed")
                    except Exception as e:
                        errors.append(f"{field}: validation error: {e}")

        return errors


class EnrichmentStage:
    """数据补全阶段。"""

    @staticmethod
    def run(data: dict) -> dict:
        enriched = dict(data)

        # 从 URL 推断缺失的 ID
        if "image_url" in enriched and enriched.get("image_url"):
            enriched.setdefault("has_image", True)

        return enriched


class ParserPipeline:
    """
    多阶段解析器流水线。

    用法：
        pipeline = ParserPipeline(parsers={
            "match_upcoming": MatchUpcomingParser(),
        })
        result = await pipeline.process(html, "match_upcoming")
    """

    def __init__(
        self,
        parsers: dict[str, SemanticParser] | None = None,
        validation_rules: dict[str, dict[str, Callable]] | None = None,
    ) -> None:
        self._parsers = parsers or {}
        self._validation_rules = validation_rules or {}
        self._stats = {
            "total": 0,
            "success": 0,
            "failed": 0,
            "by_type": {},
        }

    def register_parser(self, page_type: str, parser: SemanticParser) -> None:
        self._parsers[page_type] = parser

    async def process(self, html: str, page_type: str | None = None) -> ParseResult:
        """
        对 HTML 执行完整解析流程。

        Args:
            html: 原始 HTML
            page_type: 页面类型（可自动检测）

        Returns:
            ParseResult
        """
        self._stats["total"] += 1

        # Stage 1: Preprocess
        cleaned, detected_type = PreprocessStage.run(html)
        page_type = page_type or detected_type

        self._stats["by_type"][page_type] = self._stats["by_type"].get(page_type, 0) + 1

        # Stage 2: Semantic Parse
        parser = self._parsers.get(page_type)
        if parser is None:
            self._stats["failed"] += 1
            return ParseResult(
                data={}, page_type=page_type, success=False,
                errors=[f"No parser registered for {page_type}"],
            )

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(cleaned, "lxml")
            parsed = parser.parse(soup)
        except Exception as e:
            self._stats["failed"] += 1
            return ParseResult(
                data={}, page_type=page_type, success=False,
                errors=[f"Parse failed: {e}"],
            )

        # Stage 3: Validation
        rules = self._validation_rules.get(page_type, {})
        validation_errors = ValidationStage.run(parsed, rules)
        if validation_errors:
            logger.warning("Validation errors for %s: %s", page_type, validation_errors)

        # Stage 4: Enrichment
        enriched = EnrichmentStage.run(parsed)

        # Stage 5: Output
        self._stats["success"] += 1
        return ParseResult(
            data=enriched,
            page_type=page_type,
            success=len(validation_errors) == 0,
            errors=validation_errors,
        )

    def get_stats(self) -> dict[str, Any]:
        return dict(self._stats)
