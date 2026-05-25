"""
Semantic Parser — 语义层解析器引擎。

与旧版硬编码 CSS selector 的关键区别：
1. 每个字段有 2-3 个 selector fallback
2. 记录 selector 命中率，指导优化
3. Selector 策略与解析逻辑分离（YAML 定义）
4. 自动降级：primary selector 失效时自动 fallback

用法：
    strategies = load_strategies("match_overview.yaml")
    parser = SemanticParser(strategies)
    result = parser.parse(soup, "match_overview")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

logger = logging.getLogger("hltv.parser.semantic")


@dataclass
class SelectorStrategy:
    """
    一个字段的多层 selector 配置。

    Attributes:
        field: 字段名
        primary: 首选 CSS selector
        fallbacks: 备选 CSS selector 列表
        extractor: 提取方式
        attr: 如 extractor=attr，指定属性名
        required: 此字段缺失是否跳过整条记录
        validator: 自定义校验函数 (value) -> bool
        transform: 自定义转换函数 (value) -> new_value
    """
    field: str
    primary: str
    fallbacks: list[str] = field(default_factory=list)
    extractor: Literal["text", "href", "src", "img", "int", "float", "attr"] = "text"
    attr: str | None = None
    required: bool = False
    validator: Callable | None = None
    transform: Callable | None = None


class SemanticParser:
    """
    语义层解析器。

    接受一组 SelectorStrategy，对 soup 对象执行多层 selector 解析。
    跟踪每个 selector 的命中率。

    用法：
        strategies = [
            SelectorStrategy("team1_name", ".match-teamname",
                             fallbacks=[".team1 .team", ".team-cell:first-child .team"]),
            SelectorStrategy("match_id", ".match-wrapper",
                             extractor="attr", attr="data-match-id", required=True),
        ]
        parser = SemanticParser(strategies)
        result = parser.parse(soup)
    """

    def __init__(self, strategies: list[SelectorStrategy]) -> None:
        self._strategies = strategies

        # selector 命中率统计: {field: {selector: hit_count}}
        self._hit_stats: dict[str, dict[str, int]] = {}
        self._miss_stats: dict[str, dict[str, int]] = {}
        self._total_parses = 0
        self._success_parses = 0

    def parse(self, soup: Any) -> dict[str, Any]:
        """
        对 soup 对象执行解析。

        Args:
            soup: BeautifulSoup / selectolax 解析树

        Returns:
            解析结果 dict，包含所有字段

        Raises:
            ValueError: 如果 required 字段全部缺失
        """
        self._total_parses += 1
        result: dict[str, Any] = {}
        all_required_missing = True

        for strategy in self._strategies:
            value = self._extract_field(soup, strategy)
            if strategy.field not in self._hit_stats:
                self._hit_stats[strategy.field] = {}
                self._miss_stats[strategy.field] = {}

            if value is not None:
                self._hit_stats[strategy.field][self._find_matched_selector(soup, strategy)] = \
                    self._hit_stats[strategy.field].get(self._find_matched_selector(soup, strategy), 0) + 1

                # 后置转换
                if strategy.transform and callable(strategy.transform):
                    try:
                        value = strategy.transform(value)
                    except Exception as e:
                        logger.debug("Transform failed for %s: %s", strategy.field, e)

                # 后置校验
                if strategy.validator and callable(strategy.validator):
                    if not strategy.validator(value):
                        logger.debug("Validation failed for %s: %s", strategy.field, value)
                        continue

                result[strategy.field] = value
                if strategy.required:
                    all_required_missing = False

            else:
                # 记录失败统计
                for sel in [strategy.primary] + strategy.fallbacks:
                    self._miss_stats[strategy.field][sel] = \
                        self._miss_stats[strategy.field].get(sel, 0) + 1

        if all_required_missing and any(s.required for s in self._strategies):
            raise ValueError("All required fields missing in parse")

        self._success_parses += 1
        return result

    def parse_batch(self, soup: Any, container_selector: str) -> list[dict[str, Any]]:
        """
        对容器内的每个元素执行解析。

        Args:
            soup: 解析树
            container_selector: 容器 CSS selector

        Returns:
            解析结果列表
        """
        from src.parser import select_all

        containers = select_all(soup, container_selector)
        results = []
        for container in containers:
            try:
                result = self.parse(container)
                results.append(result)
            except ValueError:
                continue
        return results

    def _extract_field(self, soup: Any, strategy: SelectorStrategy) -> Any:
        """执行多层 selector fallback 提取。"""
        # 尝试 primary
        selectors = [strategy.primary] + strategy.fallbacks
        from src.parser import select_one, safe_text, extract_href, extract_img_url, safe_int, safe_float

        for selector in selectors:
            try:
                element = select_one(soup, selector)
                if element is None:
                    continue

                if strategy.extractor == "text":
                    value = safe_text(element)
                    if value and value.strip():
                        return value.strip()

                elif strategy.extractor == "href":
                    value = extract_href(element)
                    if value:
                        return value

                elif strategy.extractor == "src":
                    from src.parser import extract_src
                    value = extract_src(element)
                    if value:
                        return value

                elif strategy.extractor == "img":
                    value = extract_img_url(element)
                    if value:
                        return value

                elif strategy.extractor == "int":
                    return safe_int(safe_text(element))

                elif strategy.extractor == "float":
                    return safe_float(safe_text(element))

                elif strategy.extractor == "attr":
                    if strategy.attr:
                        val = element.get(strategy.attr) if hasattr(element, "get") else None
                        if val is not None:
                            return str(val)

            except Exception as e:
                logger.debug("Selector %s failed on %s: %s", selector, strategy.field, e)
                continue

        return None

    def _find_matched_selector(self, soup: Any, strategy: SelectorStrategy) -> str:
        """找到实际匹配的 selector。"""
        from src.parser import select_one

        for sel in [strategy.primary] + strategy.fallbacks:
            try:
                if select_one(soup, sel) is not None:
                    return sel
            except Exception:
                continue
        return strategy.primary

    def get_health_report(self) -> dict[str, Any]:
        """获取 selector 命中率报告。"""
        report: dict[str, Any] = {}
        for fname in self._hit_stats:
            total_hits = sum(self._hit_stats[fname].values())
            total_misses = sum(self._miss_stats.get(fname, {}).values())
            total = total_hits + total_misses
            sel_hits = self._hit_stats[fname]
            sel_misses = self._miss_stats.get(fname, {})
            all_sels = set(list(sel_hits.keys()) + list(sel_misses.keys()))
            report[fname] = {
                "total_attempts": total,
                "total_hits": total_hits,
                "hit_rate": round(total_hits / max(total, 1), 3),
                "selectors": {
                    sel: {
                        "hits": sel_hits.get(sel, 0),
                        "misses": sel_misses.get(sel, 0),
                    }
                    for sel in all_sels
                },
            }
        return {
            "total_parses": self._total_parses,
            "success_parses": self._success_parses,
            "success_rate": round(self._success_parses / max(self._total_parses, 1), 3),
            "fields": report,
        }
