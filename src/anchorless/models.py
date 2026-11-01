"""The data that flows from the sources to the screen."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from .config import SegmentConfig

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass
class Story:
    """One item from one feed, already cleaned up."""

    key: str              # stable id: a hash of the cleaned-up URL (or of the title)
    title: str
    summary: str
    outlet: str           # the source's name, e.g. "NPR"
    url: str
    published: datetime | None
    scope: str            # local | national | world
    category: str
    weight: float = 1.0
    raw_title: str = ""   # as the feed gave it, before "Live updates:" etc. were stripped
    first_seen: datetime | None = None   # filled from the store

    @property
    def when(self) -> datetime | None:
        """When the story appeared: its publish time, or when we first saw it."""
        if self.published and self.first_seen:
            return min(self.published, self.first_seen)
        return self.published or self.first_seen


@dataclass
class Cluster:
    """The same story as told by one or more outlets."""

    stories: list[Story]
    tokens: set[str] = field(default_factory=set)
    score: float = 0.0

    @property
    def lead(self) -> Story:
        """The version shown on screen."""
        return self.stories[0]

    @property
    def key(self) -> str:
        """Stable across refreshes: the earliest-seen member's key."""
        return min(self.stories, key=lambda s: (s.when is None, s.when or _EPOCH, s.key)).key

    @property
    def outlets(self) -> list[str]:
        seen: list[str] = []
        for s in self.stories:
            if s.outlet not in seen:
                seen.append(s.outlet)
        return seen

    @property
    def when(self) -> datetime | None:
        times = [s.when for s in self.stories if s.when]
        return min(times) if times else None

    def matches(self, segment: SegmentConfig) -> bool:
        return any(
            (segment.scope is None or s.scope == segment.scope)
            and (segment.category is None or s.category == segment.category)
            for s in self.stories
        )


@dataclass
class Segment:
    name: str
    clusters: list[Cluster]


@dataclass
class Rundown:
    segments: list[Segment]
    built_at: datetime
    breaking: Cluster | None = None

    @property
    def clusters(self) -> list[Cluster]:
        return [c for seg in self.segments for c in seg.clusters]

    @property
    def empty(self) -> bool:
        return not self.clusters
