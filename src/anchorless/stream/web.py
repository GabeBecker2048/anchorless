"""The browser side: a page to watch the channels and see what the station is doing.

  /                      the viewer and status page
  /api/status            everything that page shows (JSON)
  /poster/<id>.png       a still of what is on now, shown before you press play
  /static/...            the page's script (mpegts.js plays MPEG-TS in the browser)
  /fonts/...             the pixel fonts the channel uses

Read-only: nothing here changes the station. Watching from the page is the same
as watching from a TV: it starts the channel's encoder, which stops a minute
after the last viewer leaves.
"""

from __future__ import annotations

import io
import time
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from aiohttp import web

from .. import __version__

if TYPE_CHECKING:
    from .server import Station

WEB_DIR = Path(str(files("anchorless") / "web"))
FONT_DIR = Path(str(files("anchorless") / "fonts"))
POSTER_SECONDS = 30            # a poster is redrawn at most this often


def _iso(d: datetime | None) -> str | None:
    return d.astimezone(UTC).isoformat() if d else None


def status(st: Station) -> dict:
    room = st.newsroom
    rd = room.rundown
    now = datetime.now(UTC)
    tagged = {k for k, (_, until) in room.breaking_tags.items() if until > now}
    rundown = []
    if rd:
        for seg in rd.segments:
            rundown.append({"segment": seg.name, "stories": [{
                "title": c.lead.title,
                "summary": c.lead.summary,
                "outlets": c.outlets,
                "when": _iso(c.when),
                "breaking": c.key in tagged,
            } for c in seg.clusters]})
    feeds = [{
        "name": f["name"], "host": urlsplit(f["url"]).hostname, "enabled": f["enabled"],
        "stories": f["stories"], "error": f["error"], "ok_at": f["ok_at"],
    } for f in room.feed_status()]
    b = st.cfg.breaking
    return {
        "version": __version__,
        "now": _iso(now),
        "timezone": st.cfg.channel.timezone,
        "last_refresh": _iso(room.last_refresh),
        "refresh_minutes": st.cfg.rundown.refresh_minutes,
        "refresh_error": room.last_error,
        "channels": [{**ch.status(), "id": ch.info.id, "stream": ch.info.path} for ch in st.channels.values()],
        "rundown": rundown,
        "feeds": feeds,
        "alerts": [{"title": t, "when": _iso(w)} for t, w in room.store.recent_alerts(8)],
        "breaking_rule": {"enabled": b.enabled, "min_sources": b.min_sources, "window_minutes": b.window_minutes,
                          "local_min_sources": b.local_min_sources, "local_alerts": b.local_alerts,
                          "cooldown_minutes": b.cooldown_minutes},
        "idle_seconds": st.cfg.stream.idle_seconds,
    }


class Web:
    def __init__(self, station: Station) -> None:
        self.st = station
        self._posters: dict[str, tuple[float, bytes]] = {}

    async def index(self, request: web.Request) -> web.Response:
        return web.FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    async def api_status(self, request: web.Request) -> web.Response:
        return web.json_response(status(self.st), headers={"Cache-Control": "no-store"})

    async def poster(self, request: web.Request) -> web.Response:
        ch = self.st.channels.get(request.match_info["id"])
        if ch is None:
            raise web.HTTPNotFound()
        cached = self._posters.get(ch.info.id)
        if cached and time.monotonic() - cached[0] < POSTER_SECONDS:
            png = cached[1]
        else:
            png = self._draw_poster(ch)
            self._posters[ch.info.id] = (time.monotonic(), png)
        return web.Response(body=png, content_type="image/png", headers={"Cache-Control": "no-store"})

    def _draw_poster(self, ch) -> bytes:
        """The current top story as the channel draws it (no crawl or clock: a few ms)."""
        now = datetime.now(UTC)
        rd = self.st.newsroom.rundown
        theme = ch.theme
        if rd and not rd.empty:
            seg = rd.segments[0]
            img = theme.story_page(seg.clusters[0], seg.name, 1, len(seg.clusters), now)
        else:
            img = theme.empty_page(now)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "PNG", optimize=False, compress_level=3)
        return buf.getvalue()


def add_routes(app: web.Application, station: Station) -> None:
    w = Web(station)
    app.router.add_get("/", w.index)
    app.router.add_get("/api/status", w.api_status)
    app.router.add_get("/poster/{id}.png", w.poster)
    app.router.add_static("/static/", WEB_DIR / "vendor")
    app.router.add_static("/fonts/", FONT_DIR)
