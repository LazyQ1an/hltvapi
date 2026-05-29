"""
Demo download endpoint for HLTV match demos.

Provides:
- Finding demo download links on match pages
- Downloading demo files with progress tracking
- Batch download for all demos of a match
- Basic demo metadata extraction from download page
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from src.client import HLTVClient
from src.models.match import MatchDemo
from src.parser import (
    safe_text, extract_href, make_absolute_url,
    select_all,
)
from src.utils.logger import get_logger

logger = get_logger("endpoints.demos")


class DemosEndpoint:
    """Endpoints for demo discovery and download."""

    BASE_URL = "https://www.hltv.org"

    def __init__(self, client: HLTVClient) -> None:
        self._client = client

    async def get_demos(self, match_id: int) -> list[MatchDemo]:
        """Find all downloadable demos for a match.

        Scrapes the match detail page for demo download links.

        Args:
            match_id: HLTV match ID.

        Returns:
            List of MatchDemo with download URLs.
        """
        url = "{}/matches/{}/-".format(self.BASE_URL, match_id)
        soup = await self._client.get_soup(url)

        demos: list[MatchDemo] = []
        demo_links = select_all(soup, "a[href*='/download/demo/'], a[href*='download'], a[href*='.dem']")

        for link in demo_links:
            try:
                href = extract_href(link)
                if not href:
                    continue
                demo_url = make_absolute_url(href)
                if not demo_url:
                    continue
                name = safe_text(link) or "demo"
                demos.append(MatchDemo(
                    name=name,
                    url=demo_url,
                ))
            except Exception as e:
                logger.debug("Failed to parse demo link: %s", e)
                continue

        if not demos:
            logger.info("No demos found for match %d", match_id)

        return demos

    async def get_demo_metadata(self, demo_url: str) -> dict[str, Any]:
        """Fetch metadata about a demo from its download page.

        Downloads the demo page HTML (not the binary) to extract metadata.

        Args:
            demo_url: Full demo download URL.

        Returns:
            Dict with demo metadata (size, map, etc.) if available.
        """
        metadata: dict[str, Any] = {
            "url": demo_url,
            "filename": None,
            "size_bytes": None,
            "map_name": None,
        }

        try:
            html = await self._client.get(demo_url)
            # Try to extract filename from Content-Disposition or URL
            filename_match = re.search(r'filename=([^&\n]+)', html[:2000])
            if filename_match:
                metadata["filename"] = filename_match.group(1).strip('"')
            else:
                # Extract from URL
                url_path = demo_url.split("?")[0]
                metadata["filename"] = url_path.split("/")[-1] or None
        except Exception as e:
            logger.debug("Failed to fetch demo metadata: %s", e)

        return metadata

    async def download_demo(
        self,
        demo_url: str,
        output_path: str | Path,
        *,
        chunk_size: int = 8192,
    ) -> Path:
        """Download a demo file to disk.

        Uses the HLTVClient's HTTP layer (curl_cffi) for download.

        Args:
            demo_url: Full demo download URL.
            output_path: Directory or file path to save to.
            chunk_size: Download chunk size in bytes.

        Returns:
            Path to the downloaded file.
        """
        output_path = Path(output_path)
        if output_path.is_dir():
            # Generate filename from URL
            filename = demo_url.split("/")[-1].split("?")[0]
            if not filename or "." not in filename:
                demo_match = re.search(r'/demo/(\d+)', demo_url)
                demo_id = demo_match.group(1) if demo_match else str(hash(demo_url))
                filename = "demo_{}.dem".format(demo_id)
            output_path = output_path / filename

        # Ensure parent directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Download using the client's curl session for speed
        session = await self._client._get_curl_session()
        if session is None:
            # Fallback to httpx
            import httpx
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream("GET", demo_url) as response:
                    response.raise_for_status()
                    downloaded = 0
                    with open(output_path, "wb") as f:
                        async for chunk in response.aiter_bytes(chunk_size):
                            f.write(chunk)
                            downloaded += len(chunk)
            logger.info("Downloaded %s (%d bytes)", output_path.name, downloaded)
        else:
            # Use curl_cffi
            response = await session.get(demo_url, stream=True)
            response.raise_for_status()
            downloaded = 0
            with open(output_path, "wb") as f:
                async for chunk in response.aiter_content(chunk_size):
                    f.write(chunk)
                    downloaded += len(chunk)
            logger.info("Downloaded %s (%d bytes)", output_path.name, downloaded)

        return output_path

    async def download_match_demos(
        self,
        match_id: int,
        output_dir: str | Path,
    ) -> list[Path]:
        """Download all demos for a match.

        Args:
            match_id: HLTV match ID.
            output_dir: Directory to save demo files.

        Returns:
            List of downloaded file paths.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        demos = await self.get_demos(match_id)
        if not demos:
            logger.warning("No demos found for match %d", match_id)
            return []

        downloaded: list[Path] = []
        for demo in demos:
            if not demo.url:
                continue
            try:
                path = await self.download_demo(demo.url, output_dir)
                downloaded.append(path)
            except Exception as e:
                logger.error("Failed to download %s: %s", demo.url, e)
                continue

        return downloaded


__all__ = ["DemosEndpoint"]
