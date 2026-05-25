"""
Event endpoints: event listings and event details.
"""
from __future__ import annotations
from datetime import datetime
from bs4 import BeautifulSoup, Tag
from src.client import HLTVClient
from src.models.event import EventOverview, EventDetail
from src.parser import (
    safe_text, safe_int, extract_href, extract_img_url,
    make_absolute_url, parse_date_string, parse_event_id_from_url,
    select_one, select_all,
)
from src.utils.logger import get_logger

logger = get_logger("endpoints.events")

class EventsEndpoint:
    """Endpoints for event/tournament data."""

    BASE_URL = "https://www.hltv.org"

    def __init__(self, client: HLTVClient) -> None:
        self._client = client

    async def get_events(self) -> list[EventOverview]:
        """Fetch all events (ongoing, upcoming, and recent).

        Returns:
            List of EventOverview for all listed events.
        """
        url = f"{self.BASE_URL}/events"
        soup = await self._client.get_soup(url)
        events: list[EventOverview] = []

        event_elements = select_all(soup, ".event-item, .event-block, .event-col, a[href*='/events/']")
        seen_ids: set[int] = set()

        for el in event_elements:
            try:
                event = self._parse_event_overview(el)
                if event and event.id and event.id not in seen_ids:
                    seen_ids.add(event.id)
                    events.append(event)
            except Exception as e:
                logger.debug("Failed to parse event element: %s", e)
                continue

        return events

    async def get_detail(self, event_id: int) -> EventDetail:
        """Fetch full details for a specific event.

        Args:
            event_id: HLTV event ID.

        Returns:
            EventDetail with all event information.
        """
        url = f"{self.BASE_URL}/events/{event_id}/-"
        soup = await self._client.get_soup(url)
        return self._parse_event_detail(soup, event_id)

    async def get_ongoing(self) -> list[EventOverview]:
        """Fetch only ongoing events.

        Returns:
            List of ongoing events.
        """
        events = await self.get_events()
        return [e for e in events if e.is_ongoing]

    def _parse_event_overview(self, element: Tag) -> EventOverview | None:
        """Parse event overview from listing page."""
        link = element if element.name == "a" else select_one(element, "a")
        href = extract_href(link) if link else None
        event_id = parse_event_id_from_url(href)

        if not event_id:
            data_id = element.get("data-event-id") or element.get("data-id")
            if data_id:
                event_id = safe_int(str(data_id))

        if not event_id:
            return None

        name = safe_text(select_one(element, ".event-name, .name, .event-title, h3, h4"))
        
        logo_el = select_one(element, "img")
        logo = extract_img_url(logo_el)

        # Date
        date_el = select_one(element, ".date, .event-date, .date-range, .date-cell")
        date_text = safe_text(date_el)
        dates = self._parse_date_range(date_text)

        prize_el = select_one(element, ".prize, .prize-pool, .prize-money")
        prize = safe_text(prize_el) or None

        location_el = select_one(element, ".location, .event-location, .city, .country")
        location = safe_text(location_el) or None

        teams_el = select_one(element, ".teams, .team-count")
        teams_count = safe_int(safe_text(teams_el))

        # Tier detection
        tier_el = select_one(element, ".tier, .event-tier, .ranking-tier")
        tier = safe_text(tier_el) or None

        # Check for "ongoing" indicator
        ongoing_text = safe_text(element)
        is_ongoing = any(w in ongoing_text.lower() for w in ["live", "ongoing", "playoffs"])

        return EventOverview(
            id=event_id,
            name=name,
            logo=logo,
            date_start=dates[0] if len(dates) > 0 else None,
            date_end=dates[1] if len(dates) > 1 else None,
            prize_pool=prize,
            location=location,
            teams_count=teams_count,
            tier=tier,
            is_ongoing=is_ongoing,
        )

    def _parse_date_range(self, text: str) -> tuple[datetime | None, datetime | None]:
        """Parse a date range string like '2024-03-15 - 2024-03-20'."""
        if not text:
            return None, None
        
        import re
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", text)
        results: list[datetime | None] = []
        for d in dates[:2]:
            results.append(parse_date_string(d))
        
        start = results[0] if len(results) > 0 else None
        end = results[1] if len(results) > 1 else None
        return start, end

    def _parse_event_detail(self, soup: BeautifulSoup, event_id: int) -> EventDetail:
        """Parse full event detail page."""
        detail = EventDetail(id=event_id)

        name_el = select_one(soup, ".event-name, .event-title, h1")
        detail.name = safe_text(name_el)

        logo_el = select_one(soup, "img.event-logo, img[class*='logo']")
        detail.logo = extract_img_url(logo_el)

        date_el = select_one(soup, ".date, .event-date, .date-range, .event-dates")
        date_text = safe_text(date_el)
        dates = self._parse_date_range(date_text)
        detail.date_start = dates[0]
        detail.date_end = dates[1]

        prize_el = select_one(soup, ".prize, .prize-pool, .prize-money")
        detail.prize_pool = safe_text(prize_el) or None

        location_el = select_one(soup, ".location, .event-location, .city, .event-city")
        detail.location = safe_text(location_el) or None

        teams_el = select_one(soup, ".teams, .team-count, .participants")
        teams_text = safe_text(teams_el)
        detail.teams_count = safe_int(teams_text)

        tier_el = select_one(soup, ".tier, .event-tier")
        detail.tier = safe_text(tier_el) or None

        format_el = select_one(soup, ".format, .event-format, .format-description")
        detail.format_description = safe_text(format_el) or None

        organizer_el = select_one(soup, ".organizer, .event-organizer, .organized-by")
        detail.organizer = safe_text(organizer_el) or None

        # Streams
        stream_links = select_all(soup, "a[href*='twitch.tv'], a[href*='youtube.com'], a[href*='stream']")
        for s in stream_links:
            name = safe_text(s) or "Stream"
            url = make_absolute_url(extract_href(s))
            if url:
                detail.streams.append({"name": name, "url": url})

        # Detect ongoing
        detail.is_ongoing = bool(select_one(soup, ".live, .ongoing, .in-progress"))

        return detail


__all__ = ["EventsEndpoint"]
