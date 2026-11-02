"""RSS and Atom feeds."""

from __future__ import annotations

import asyncio
import calendar
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime

import feedparser
import httpx

from .. import __version__
from ..config import SourceConfig
from ..models import Story
from ..text import clean_headline, clean_text, is_filler, shorten, story_key

log = logging.getLogger(__name__)

USER_AGENT = f"anchorless/{__version__} (RSS reader)"
SUMMARY_LIMIT = 320


@dataclass
class FeedState:
    """What the last fetch of a feed returned, for conditional requests."""

    etag: str | None = None
    modified: str | None = None
    stories: list[Story] | None = None
    error: str | None = None
    ok_at: datetime | None = None


def _published(entry: feedparser.FeedParserDict) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            try:
                return datetime.fromtimestamp(calendar.timegm(t), UTC)
            except (OverflowError, ValueError):
                return None
    return None


def parse_feed(body: bytes | str, source: SourceConfig) -> list[Story]:
    """Feed XML to stories. Entries without a title are skipped."""
    feed = feedparser.parse(body)
    excludes = [re.compile(p, re.I) for p in source.exclude]
    stories = []
    for entry in feed.entries:
        raw_title = clean_text(entry.get("title"))
        title = clean_headline(raw_title)
        if not title or is_filler(title):
            continue
        url = (entry.get("link") or "").strip()
        if any(p.search(raw_title) or p.search(url) for p in excludes):
            continue
        summary = shorten(clean_text(entry.get("summary") or entry.get("description")), SUMMARY_LIMIT)
        if summary.lower() == title.lower():
            summary = ""
        stories.append(Story(
            key=story_key(url, title), title=title, summary=summary, outlet=source.name, url=url,
            published=_published(entry), scope=source.scope, category=source.category, weight=source.weight, raw_title=raw_title,
        ))
    return stories


class RssFetcher:
    """Fetches all RSS sources at once, remembering ETags between refreshes."""

    def __init__(self, timeout: float = 15.0) -> None:
        self.state: dict[str, FeedState] = {}
        self.timeout = timeout

    async def _fetch(self, client: httpx.AsyncClient, source: SourceConfig) -> list[Story]:
        st = self.state.setdefault(source.url, FeedState())
        headers = {}
        if st.stories is not None:
            if st.etag:
                headers["If-None-Match"] = st.etag
            if st.modified:
                headers["If-Modified-Since"] = st.modified
        try:
            r = await client.get(source.url, headers=headers)
            if r.status_code == 304 and st.stories is not None:
                st.error = None
                st.ok_at = datetime.now(UTC)
                return st.stories
            r.raise_for_status()
            stories = parse_feed(r.content, source)
        except (httpx.HTTPError, ValueError) as err:
            st.error = f"{type(err).__name__}: {err}"[:200]
            log.warning("feed %s (%s) failed: %s", source.name, source.url, st.error)
            # Keep showing what it last gave us; it ages out on its own.
            return st.stories or []
        st.etag = r.headers.get("etag")
        st.modified = r.headers.get("last-modified")
        st.stories = stories
        st.error = None
        st.ok_at = datetime.now(UTC)
        return stories

    # Feeds on the same site are fetched one after another, this far apart: some
    # sites answer a burst of requests with 429 Too Many Requests.
    SAME_HOST_GAP = 3.0

    async def _fetch_host(self, client: httpx.AsyncClient, sources: list[SourceConfig]) -> list[Story]:
        out: list[Story] = []
        for i, source in enumerate(sources):
            if i:
                await asyncio.sleep(self.SAME_HOST_GAP)
            out += await self._fetch(client, source)
        return out

    async def fetch_all(self, sources: list[SourceConfig]) -> list[Story]:
        enabled = [s for s in sources if s.enabled and s.type == "rss"]
        by_host: dict[str, list[SourceConfig]] = {}
        for s in enabled:
            by_host.setdefault(httpx.URL(s.url).host, []).append(s)
        async with httpx.AsyncClient(
            timeout=self.timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT},
        ) as client:
            results = await asyncio.gather(*(self._fetch_host(client, group) for group in by_host.values()))
        return [story for batch in results for story in batch]
