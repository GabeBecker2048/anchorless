"""The browser side: a page to watch the channels and see what the station is doing.

  /                      the viewer and status page
  /api/status            everything that page shows (JSON)
  /poster/<id>.png       a still of what is on now, shown before you press play
  /static/...            the page's script (mpegts.js plays MPEG-TS in the browser)
  /fonts/...             the pixel fonts the channel uses

Watching from the page is the same as watching from a TV: it starts the
channel's encoder, which stops a minute after the last viewer leaves.

  /settings              the settings page (needs a password: see admin.py)
  /api/settings          GET the settings, PATCH changes (written to the config file)
  /api/feeds/check       try a feed URL before adding it
  /api/login, /api/logout
"""

from __future__ import annotations

import io
import logging
import time
from datetime import UTC, datetime
from html import escape
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import httpx
from aiohttp import web

from .. import __version__
from ..config import SourceConfig
from ..netguard import BlockedURL, check_url, guard_hooks
from ..settings import SettingsError
from ..sources.rss import USER_AGENT, parse_feed
from .admin import Admin

if TYPE_CHECKING:
    from .server import Station

log = logging.getLogger(__name__)

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
        # Only the channels offered on the web (show_on "both" or "web").
        "channels": [{**ch.status(), "id": ch.info.id, "stream": ch.info.path, "hls": f"/hls/{ch.info.id}.m3u8"}
                     for ch in st.channels.values() if ch.info.on_web],
        "rundown": rundown,
        "feeds": feeds,
        "alerts": [{"title": t, "when": _iso(w)} for t, w in room.store.recent_alerts(8)],
        "breaking_rule": {"enabled": b.enabled, "min_sources": b.min_sources, "window_minutes": b.window_minutes,
                          "local_min_sources": b.local_min_sources, "local_alerts": b.local_alerts,
                          "cooldown_minutes": b.cooldown_minutes},
        "idle_seconds": st.cfg.stream.idle_seconds,
        "limits": {"max_sessions": st.cfg.stream.max_sessions, "max_viewers": st.cfg.stream.max_viewers,
                   "sessions": st.sessions(), "viewers": st.viewers()},
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


class SettingsApi:
    def __init__(self, station: Station) -> None:
        self.st = station
        self.admin = Admin(station.cfg)

    async def page(self, request: web.Request) -> web.Response:
        return web.FileResponse(WEB_DIR / "settings.html", headers={"Cache-Control": "no-cache"})

    def _settings(self):
        if self.st.settings is None:
            raise web.HTTPNotFound(text='{"error": "no config file"}', content_type="application/json")
        return self.st.settings

    async def get(self, request: web.Request) -> web.Response:
        self.admin.check(request)
        snap = self._settings().snapshot()
        snap["live"] = {ch.info.id: {"viewers": len(ch.clients) + ch.hls_viewers(), "running": bool(ch.session),
                                     "pending": ch.pending is not None} for ch in self.st.channels.values()}
        snap["config_error"] = self.st.config_error
        snap["history"] = self.st.history.recent(20)
        return web.json_response(snap, headers={"Cache-Control": "no-store"})

    async def patch(self, request: web.Request) -> web.Response:
        self.admin.check(request, write=True)
        settings = self._settings()
        try:
            body = await request.json()
        except Exception:
            raise web.HTTPBadRequest(text='{"error": "expected JSON"}', content_type="application/json") from None
        ops = list(body.get("ops") or [])
        for op in ops:      # a feed being added or changed must be on the public internet
            if isinstance(op, dict) and op.get("op") in ("feed_add", "feed_edit"):
                try:
                    await check_url(str((op.get("value") or {}).get("url", "")).strip(),
                                    self.st.cfg.feeds.allow_private)
                except BlockedURL as err:
                    return web.json_response({"error": str(err)}, status=400)
        try:
            cfg = await settings.patch(ops)
        except SettingsError as err:
            return web.json_response({"error": str(err), "keys": getattr(err, "keys", [])}, status=err.status)
        except (KeyError, TypeError, ValueError, StopIteration) as err:
            return web.json_response({"error": f"bad change: {err}"}, status=400)
        self.st.config_version = settings.read().version
        result = await self.st.reload(cfg, restart_now=body.get("apply") == "now",
                                      source=f"settings page ({self.admin.client_ip(request)})")
        log.info("settings saved from %s: %d change(s)", self.admin.client_ip(request), len(body.get("ops") or []))
        return web.json_response({"ok": True, **result})

    async def check_feed(self, request: web.Request) -> web.Response:
        self.admin.check(request, write=True)
        body = await request.json()
        url = str(body.get("url", "")).strip()
        allow_private = self.st.cfg.feeds.allow_private
        try:
            await check_url(url, allow_private)
        except BlockedURL as err:
            return web.json_response({"ok": False, "error": str(err)})
        src = SourceConfig(name=str(body.get("name") or "check"), url=url, compressed=body.get("compressed", True))
        headers = {"User-Agent": USER_AGENT}
        if not src.compressed:
            headers["Accept-Encoding"] = "identity"
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True,
                                         event_hooks=guard_hooks(allow_private)) as client:
                r = await client.get(url, headers=headers)
            r.raise_for_status()
            stories = parse_feed(r.content, src)
        except Exception as err:   # anything: tell the person, never fail the page
            return web.json_response({"ok": False, "error": f"{type(err).__name__}: {err}"[:300]})
        newest = max(stories, key=lambda s: s.published or datetime.min.replace(tzinfo=UTC), default=None)
        return web.json_response({"ok": bool(stories), "stories": len(stories),
                                  "newest": newest.title if newest else None,
                                  "error": None if stories else "no stories found - is it an RSS/Atom feed?"})


# The pages run only their own files: no inline script or style, nothing from elsewhere.
# blob: is the stream (mpegts.js feeds the video through a MediaSource); data: is the favicon.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "media-src 'self' blob:; worker-src 'self' blob:; connect-src 'self'; font-src 'self'; "
       "object-src 'none'; base-uri 'none'; form-action 'self'")


async def security_headers(request: web.Request, response: web.StreamResponse) -> None:
    """On every response (streams too: this runs as headers go out, unlike a middleware)."""
    h = response.headers
    h["X-Content-Type-Options"] = "nosniff"
    h["Referrer-Policy"] = "same-origin"
    h["Server"] = "anchorless"
    admin = request.path == "/settings" or request.path.startswith("/api/")
    if response.content_type == "text/html":
        h["Content-Security-Policy"] = CSP + ("; frame-ancestors 'none'" if admin else "")
    if admin:               # the settings can't be framed by another site (clickjacking)
        h["X-Frame-Options"] = "DENY"


# The viewer page and its files: [web] require_https. (The settings page and its API
# have their own rule, [admin] require_https; the TV side is never https-only.)
VIEWER_PATHS = ("/assets/", "/static/", "/fonts/", "/poster/")
HTTPS_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Anchorless: use https</title>
<meta name="viewport" content="width=device-width, initial-scale=1"></head><body>
<h1>Use https</h1><p>This page is only available over https ([web] require_https in the config).
Open it through your https address, e.g. <a href="https://{host}/">https://{host}/</a>.</p></body></html>"""


def add_routes(app: web.Application, station: Station) -> None:
    app.on_response_prepare.append(security_headers)
    w = Web(station)
    api = SettingsApi(station)

    @web.middleware
    async def viewer_https(request: web.Request, handler):
        p = request.path
        if (p == "/" or p == "/api/status" or p.startswith(VIEWER_PATHS)) and \
                not api.admin.https_ok(request, station.cfg.web.require_https):
            host = escape(request.headers.get("X-Forwarded-Host") or request.host.split(":")[0])
            return web.Response(status=403, text=HTTPS_PAGE.format(host=host), content_type="text/html")
        return await handler(request)

    app.middlewares.append(viewer_https)
    app.router.add_get("/settings", api.page)
    app.router.add_get("/api/settings", api.get)
    app.router.add_patch("/api/settings", api.patch)
    app.router.add_post("/api/feeds/check", api.check_feed)
    app.router.add_post("/api/login", api.admin.login)
    app.router.add_post("/api/logout", api.admin.logout)
    app.router.add_get("/", w.index)
    app.router.add_get("/api/status", w.api_status)
    app.router.add_get("/poster/{id}.png", w.poster)
    app.router.add_static("/static/", WEB_DIR / "vendor")
    app.router.add_static("/assets/", WEB_DIR / "assets")
    app.router.add_static("/fonts/", FONT_DIR)
