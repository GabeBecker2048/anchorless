"""Deciding when a story is big and new enough to interrupt the rundown."""

from __future__ import annotations

from datetime import datetime, timedelta

from .config import BreakingConfig
from .models import Cluster
from .store import Store
from .text import similarity


def _prefixed(cluster: Cluster, prefixes: list[str]) -> bool:
    return any((s.raw_title or s.title).upper().startswith(p.upper()) for s in cluster.stories for p in prefixes)


def _already_alerted(cluster: Cluster, alerts: list[tuple[str, set[str], datetime]]) -> bool:
    keys = {s.key for s in cluster.stories} | {cluster.key}
    return any(k in keys or similarity(cluster.tokens, tokens) >= 0.5 for k, tokens, _ in alerts)


def pick_breaking(clusters: list[Cluster], cfg: BreakingConfig, store: Store, now: datetime) -> Cluster | None:
    """The story to break in with now, if any (and record it so it is never repeated).

    A story qualifies when it appeared within ``window_minutes`` and either at
    least ``min_sources`` outlets already carry it, or a headline is marked
    "BREAKING:". At most one alert per ``cooldown_minutes``.
    """
    if not cfg.enabled:
        return None
    last = store.last_alert_at()
    if last and now - last < timedelta(minutes=cfg.cooldown_minutes):
        return None
    window = timedelta(minutes=cfg.window_minutes)
    alerts = store.alerts()
    for cluster in clusters:  # best first
        when = cluster.when
        if when is None or now - when > window:
            continue
        if len(cluster.outlets) < cfg.min_sources and not _prefixed(cluster, cfg.title_prefixes):
            continue
        if _already_alerted(cluster, alerts):
            continue
        store.record_alert(cluster.key, cluster.lead.title, cluster.tokens, now)
        return cluster
    return None
