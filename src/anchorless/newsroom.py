"""The newsroom: refreshes the sources on a timer and keeps the current rundown."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .breaking import pick_breaking
from .config import Config
from .models import Cluster, Rundown
from .pipeline import all_clusters, build_rundown
from .sources.rss import RssFetcher
from .store import Store

log = logging.getLogger(__name__)

STALE_ALERT = timedelta(minutes=15)


class Newsroom:
    def __init__(self, cfg: Config, store: Store | None = None) -> None:
        self.cfg = cfg
        self.store = store or Store(Path(cfg.data.dir) / "anchorless.sqlite3")
        self.fetcher = RssFetcher()
        self.rundown: Rundown | None = None
        self.version = 0                      # bumps on every new rundown
        # Alerts waiting for the next page boundary, with when they were raised.
        self.breaking_queue: list[tuple[Cluster, datetime]] = []
        # Cluster key -> (headline, until when it carries the BREAKING tag in the crawl).
        self.breaking_tags: dict[str, tuple[str, datetime]] = {}
        self.last_refresh: datetime | None = None
        self.last_error: str | None = None
        self.changed = asyncio.Event()

    async def refresh(self, now: datetime | None = None) -> Rundown:
        now = now or datetime.now(UTC)
        cold_start = self.store.is_empty()
        stories = await self.fetcher.fetch_all(self.cfg.source)
        self.store.mark_seen(stories, now)
        self.store.prune(now)
        clusters = all_clusters(stories, self.cfg, now)
        rundown = build_rundown(clusters, self.cfg, now)

        # On the very first run every undated story looks brand new: no alerts then.
        if not cold_start:
            hit = pick_breaking(clusters, self.cfg.breaking, self.store, now)
            if hit:
                log.info("BREAKING: %s (%d outlets)", hit.lead.title, len(hit.outlets))
                self.breaking_queue.append((hit, now))
                rundown.breaking = hit
                self.add_breaking_tag(hit, now)
        self.breaking_tags = {k: v for k, v in self.breaking_tags.items() if v[1] > now}

        failed = [st for st in self.fetcher.state.values() if st.error]
        log.info("refresh: %d stories from %d feeds (%d failed), %d grouped, %d in the rundown",
                 len(stories), len(self.fetcher.state), len(failed), len(clusters), len(rundown.clusters))
        self.rundown = rundown
        self.version += 1
        self.last_refresh = now
        self.changed.set()
        self.changed.clear()
        return rundown

    def add_breaking_tag(self, cluster: Cluster, now: datetime) -> None:
        until = now + timedelta(minutes=self.cfg.breaking.crawl_tag_minutes)
        self.breaking_tags[cluster.key] = (cluster.lead.title, until)

    def take_breaking(self, now: datetime) -> Cluster | None:
        """The next alert to play. One raised while nobody watched is stale after 15 min
        (it still carries the BREAKING tag in the crawl)."""
        while self.breaking_queue:
            cluster, raised = self.breaking_queue.pop(0)
            if now - raised <= STALE_ALERT:
                return cluster
        return None

    def crawl_items(self, now: datetime) -> list[tuple[str, bool]]:
        """The crawl: tagged breaking stories first, then the rundown's headlines."""
        tagged = {k: title for k, (title, until) in self.breaking_tags.items() if until > now}
        items = [(title, True) for title in tagged.values()]
        if self.rundown:
            items += [(c.lead.title, False) for c in self.rundown.clusters if c.key not in tagged]
        return items

    async def run(self) -> None:
        """Refresh forever. Fetching is cheap, so it runs even with no viewers."""
        interval = self.cfg.rundown.refresh_minutes * 60
        while True:
            try:
                await self.refresh()
                self.last_error = None
            except Exception as err:  # never let one bad refresh stop the channel
                self.last_error = f"{type(err).__name__}: {err}"
                log.exception("refresh failed")
            await asyncio.sleep(interval)

    def feed_status(self) -> list[dict]:
        out = []
        for src in self.cfg.source:
            st = self.fetcher.state.get(src.url)
            out.append({
                "name": src.name, "url": src.url, "enabled": src.enabled,
                "stories": len(st.stories) if st and st.stories else 0,
                "error": st.error if st else None,
                "ok_at": st.ok_at.isoformat() if st and st.ok_at else None,
            })
        return out
