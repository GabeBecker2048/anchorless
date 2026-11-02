"""Stories in, rundown out: group, rank and pick stories for each segment."""

from __future__ import annotations

import math
from collections import Counter
from datetime import UTC, datetime, timedelta

from .config import Config
from .models import Cluster, Rundown, Segment, Story
from .text import similarity, title_tokens

# A story's freshness halves every this many hours.
FRESHNESS_HALF_LIFE_HOURS = 6.0
# Each extra outlet carrying a story adds this much to its score.
EXTRA_OUTLET_BONUS = 1.0

_FAR_FUTURE = datetime(9999, 1, 1, tzinfo=UTC)


def recent(stories: list[Story], now: datetime, max_age: timedelta) -> list[Story]:
    """Drop stories older than ``max_age`` (by publish time, or first seen)."""
    cutoff = now - max_age
    return [s for s in stories if s.when is None or (cutoff <= s.when <= now + timedelta(hours=1))]


def cluster_stories(stories: list[Story], threshold: float) -> list[Cluster]:
    """Group the same story from different feeds and outlets together."""
    clusters: list[Cluster] = []
    by_key: dict[str, Cluster] = {}
    member_tokens: list[list[set[str]]] = []
    # Oldest first, so a cluster's first member is where the story broke.
    ordered = sorted(stories, key=lambda s: (s.when is None, s.when or _FAR_FUTURE, s.key))
    for story in ordered:
        tokens = title_tokens(story.title)
        target = by_key.get(story.key)
        if target is None:
            best, best_sim = None, threshold
            for i in range(len(clusters)):
                sim = max(similarity(tokens, t) for t in member_tokens[i])
                if sim >= best_sim:
                    best, best_sim = i, sim
            if best is not None:
                target = clusters[best]
                member_tokens[best].append(tokens)
        if target is None:
            target = Cluster(stories=[], tokens=set())
            clusters.append(target)
            member_tokens.append([tokens])
        target.stories.append(story)
        target.tokens |= tokens
        by_key[story.key] = target
    for c in clusters:
        c.stories.sort(key=_lead_preference)
    return clusters


def _bag(cluster: Cluster) -> Counter[str]:
    bag: Counter[str] = Counter()
    for s in cluster.stories:
        for t in title_tokens(s.title):
            bag[t] += 2
        for t in title_tokens(s.summary):
            bag[t] += 1
    return bag


def merge_similar(clusters: list[Cluster], threshold: float) -> list[Cluster]:
    """Second pass: merge clusters whose headlines *and* summaries share rare words.

    Different outlets word the same story differently ("Learjet with 9 aboard
    crashes" vs "Private jet with 9 people on board crashes"), so headline
    overlap alone misses some. TF-IDF cosine weighs rare words such as names
    and places above common ones.
    """
    if len(clusters) < 2:
        return clusters
    bags = [_bag(c) for c in clusters]
    df: Counter[str] = Counter(t for b in bags for t in b)
    n = len(bags)
    vecs = []
    for b in bags:
        v = {t: (1 + math.log(c)) * math.log(n / df[t]) for t, c in b.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vecs.append({t: x / norm for t, x in v.items()})

    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    index: dict[str, list[int]] = {}
    for i, v in enumerate(vecs):
        for t in v:
            index.setdefault(t, []).append(i)
    for i, a in enumerate(vecs):
        candidates = {j for t in a for j in index[t] if j > i}
        for j in candidates:
            b = vecs[j]
            small, big = (a, b) if len(a) <= len(b) else (b, a)
            if sum(x * big.get(t, 0.0) for t, x in small.items()) >= threshold:
                parent[find(j)] = find(i)

    groups: dict[int, Cluster] = {}
    for i, c in enumerate(clusters):
        root = find(i)
        if root not in groups:
            groups[root] = Cluster(stories=list(c.stories), tokens=set(c.tokens))
        elif groups[root] is not c:
            groups[root].stories.extend(c.stories)
            groups[root].tokens |= c.tokens
    merged = list(groups.values())
    for c in merged:
        c.stories.sort(key=_lead_preference)
    return merged


def _lead_preference(s: Story) -> tuple:
    # Show the version with a summary, from the highest-weighted source, seen first.
    return (not s.summary, -s.weight, s.when is None, s.when or _FAR_FUTURE)


def score(cluster: Cluster, now: datetime) -> float:
    when = cluster.when
    age_hours = max(0.0, (now - when).total_seconds() / 3600) if when else FRESHNESS_HALF_LIFE_HOURS
    freshness = 0.5 ** (age_hours / FRESHNESS_HALF_LIFE_HOURS)
    weight = max(s.weight for s in cluster.stories)
    return weight * freshness * (1 + EXTRA_OUTLET_BONUS * (len(cluster.outlets) - 1))


def all_clusters(stories: list[Story], cfg: Config, now: datetime) -> list[Cluster]:
    """Every current story, grouped across outlets and ranked best first."""
    pool = recent(stories, now, timedelta(hours=cfg.rundown.max_story_age_hours))
    clusters = cluster_stories(pool, cfg.rundown.same_story_similarity)
    clusters = merge_similar(clusters, cfg.rundown.same_story_text_similarity)
    for c in clusters:
        c.score = score(c, now)
    return sorted(clusters, key=lambda c: c.score, reverse=True)


def build_rundown(clusters: list[Cluster], cfg: Config, now: datetime) -> Rundown:
    """Fill each segment with its best stories; no story appears twice."""
    used: set[int] = set()
    segments = []
    for seg_cfg in cfg.rundown.segment:
        picked = []
        for c in clusters:
            if len(picked) >= seg_cfg.stories:
                break
            if id(c) not in used and c.matches(seg_cfg):
                picked.append(c)
                used.add(id(c))
        if picked:
            name = seg_cfg.name.replace("{city}", cfg.location.city or "LOCAL").upper()
            segments.append(Segment(name=name, clusters=picked))
    return Rundown(segments=segments, built_at=now)
