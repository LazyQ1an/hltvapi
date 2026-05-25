"""
Results endpoint: historical match results with pagination.
(May use the MatchesEndpoint.get_results internally or provide
an independent implementation.)
"""
from __future__ import annotations
from src.client import HLTVClient
from src.models.match import MatchOverview
from src.endpoints.matches import MatchesEndpoint
from src.utils.logger import get_logger

logger = get_logger("endpoints.results")

class ResultsEndpoint:
    """Endpoints for historical match results."""

    def __init__(self, client: HLTVClient) -> None:
        self._client = client
        self._matches = MatchesEndpoint(client)

    async def get_results(
        self,
        page: int = 1,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[MatchOverview]:
        """Fetch historical match results.

        Args:
            page: Page number.
            start_date: Filter start date (YYYY-MM-DD).
            end_date: Filter end date (YYYY-MM-DD).

        Returns:
            List of completed match overviews.
        """
        return await self._matches.get_results(
            page=page,
            start_date=start_date,
            end_date=end_date,
        )

    async def get_by_date_range(
        self,
        start_date: str,
        end_date: str,
    ) -> list[MatchOverview]:
        """Fetch results within a specific date range.

        Args:
            start_date: Start date (YYYY-MM-DD).
            end_date: End date (YYYY-MM-DD).

        Returns:
            List of matches in the range.
        """
        all_matches: list[MatchOverview] = []
        page = 1
        while True:
            matches = await self.get_results(
                page=page,
                start_date=start_date,
                end_date=end_date,
            )
            if not matches:
                break
            all_matches.extend(matches)
            page += 1
            if page > 20:  # Safety limit
                break
        return all_matches


__all__ = ["ResultsEndpoint"]
