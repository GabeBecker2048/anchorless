"""Deciding when a story is big and new enough to interrupt the rundown."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from .config import BreakingConfig
from .models import Cluster
from .store import Store
from .text import similarity

log = logging.getLogger(__name__)
_logged: set[str] = set()   # local stories already logged in "log" mode


def _prefixed(cluster: Cluster, prefixes: list[str]) -> bool:
    return any((s.raw_title or s.title).upper().startswith(p.upper()) for s in cluster.stories for p in prefixes)


def _already_alerted(cluster: Cluster, alerts: list[tuple[str, set[str], datetime]]) -> bool:
    keys = {s.key for s in cluster.stories} | {cluster.key}
    return any(k in keys or similarity(cluster.tokens, tokens) >= 0.5 for k, tokens, _ in alerts)


def pick_breaking(clusters: list[Cluster], cfg: BreakingConfig, store: Store, now: datetime) -> Cluster | None:
    """The story to break in with now, if any (and record it so it is never repeated).

    A story qualifies when it appeared within ``window_minutes`` and either at
    least ``min_sources`` outlets already carry it, or a headline is marked
    "BREAKING:". At most one alert per ``cooldown_minutes``. A story only local
    outlets carry needs ``local_min_sources`` of them instead.
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
        local = all(s.scope == "local" for s in cluster.stories)
        if local and cfg.local_alerts == "off":
            continue
        need = cfg.local_min_sources if local else cfg.min_sources
        if len(cluster.outlets) < need and not _prefixed(cluster, cfg.title_prefixes):
            continue
        if _already_alerted(cluster, alerts):
            continue
        if local and cfg.local_alerts == "log":
            if cluster.key not in _logged:
                _logged.add(cluster.key)
                log.info("local story would break in (local_alerts = log): %s (%s)",
                         cluster.lead.title, ", ".join(cluster.outlets))
            continue
        store.record_alert(cluster.key, cluster.lead.title, cluster.tokens, now)
        return cluster
    return None
