"""
News/article endpoints for HLTV.
"""
from __future__ import annotations
from bs4 import BeautifulSoup, Tag
from src.client import HLTVClient
from src.models.news import NewsArticle, NewsDetail, NewsListResponse
from src.parser import (
    safe_text, extract_href, extract_img_url,
    make_absolute_url, parse_date_string, select_one, select_all,
)
from src.utils.logger import get_logger

logger = get_logger("endpoints.news")

class NewsEndpoint:
    """Endpoints for news and article data."""

    BASE_URL = "https://www.hltv.org"

    def __init__(self, client: HLTVClient) -> None:
        self._client = client

    async def get_news(self, offset: int = 0, limit: int = 30) -> NewsListResponse:
        """Fetch news article listings.

        HLTV redesigned their site — the /news page now returns 404.
        News articles are fetched from the homepage sidebar (.activitylist).

        Args:
            offset: Pagination offset (note: HLTV has no news archive pagination).
            limit: Maximum number of articles to return.

        Returns:
            NewsListResponse with article list.
        """
        # Fetch news from the homepage sidebar activity feed
        url = f"{self.BASE_URL}"
        soup = await self._client.get_soup(url)
        response = NewsListResponse(offset=offset)

        # News links are in the .activitylist sidebar
        article_elements = select_all(soup, ".activitylist a[href*='/news/']")
        seen_ids: set[int] = set()

        for el in article_elements:
            try:
                article = self._parse_article(el)
                if article and article.id and article.id not in seen_ids:
                    seen_ids.add(article.id)
                    response.articles.append(article)
                    if len(response.articles) >= limit:
                        break
            except Exception as e:
                logger.debug("Failed to parse news article: %s", e)
                continue

        response.total = len(response.articles)
        return response

    async def get_detail(self, article_id: int) -> NewsDetail:
        """Fetch full article content.

        Args:
            article_id: HLTV news article ID.

        Returns:
            NewsDetail with full content.
        """
        url = f"{self.BASE_URL}/news/{article_id}/-"
        soup = await self._client.get_soup(url)
        return self._parse_article_detail(soup, article_id)

    async def get_latest(self) -> list[NewsArticle]:
        """Fetch the latest news articles.

        Returns:
            List of recent news articles.
        """
        response = await self.get_news(offset=0, limit=10)
        return response.articles

    def _parse_article(self, element: Tag) -> NewsArticle | None:
        """Parse a news article from listing page.

        HLTV sidebar format (activitylist):
        <div class="activitylist">
          <a href="/news/44630/...">Title text here123</a>
          ...
        </div>

        The link text is the title + comment count appended.
        """
        link = element if element.name == "a" else select_one(element, "a[href*='/news/']")
        if not link:
            return None

        href = extract_href(link)
        if not href:
            return None

        # Extract article ID from URL
        import re
        m = re.search(r"/news/(\d+)/", href)
        if not m:
            return None
        article_id = int(m.group(1))

        # Title: link text with trailing number (view count) stripped
        raw_title = safe_text(link)
        # Remove trailing numbers that are view counts
        title_clean = re.sub(r"\d+$", "", raw_title).strip()
        if not title_clean:
            title_clean = raw_title

        url = make_absolute_url(href)
        # Check for an image inside the link
        image = extract_img_url(select_one(link, "img"))

        return NewsArticle(
            id=article_id,
            title=title_clean,
            url=url,
            image=image,
        )

    def _parse_article_detail(self, soup: BeautifulSoup, article_id: int) -> NewsDetail:
        """Parse full article detail page."""
        detail = NewsDetail(id=article_id)

        title_el = select_one(soup, "h1, .news-title, .article-title, .headline")
        detail.title = safe_text(title_el)

        desc_el = select_one(soup, ".summary, .article-summary, .news-summary, .lead, .article-lead")
        detail.description = safe_text(desc_el) or None

        date_el = select_one(soup, ".date, .article-date, time[datetime]")
        if date_el:
            date_str = date_el.get("datetime", safe_text(date_el))
            detail.date = parse_date_string(str(date_str))

        author_el = select_one(soup, ".author, .article-author, .byline, .writer")
        detail.author = safe_text(author_el) or None

        image_el = select_one(soup, ".featured-image img, .article-image img, img[class*='featured']")
        detail.image = extract_img_url(image_el)

        # Full content
        content_el = select_one(soup, ".article-content, .news-body, .post-body, .content-text, .article-text")
        if content_el:
            detail.content = str(content_el)

        category_el = select_one(soup, ".category, .tag, .news-category")
        detail.category = safe_text(category_el) or None

        # Related articles
        related_elements = select_all(soup, ".related-item, .related-article, a[href*='/news/']")
        seen = set()
        for el in related_elements:
            try:
                article = self._parse_article(el)
                if article and article.id and article.id != article_id and article.id not in seen:
                    seen.add(article.id)
                    detail.related_articles.append(article)
            except Exception:
                continue

        return detail


__all__ = ["NewsEndpoint"]
