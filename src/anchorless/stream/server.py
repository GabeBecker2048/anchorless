"""The HTTP side: a Live TV tuner for Jellyfin (or any IPTV client).

  /playlist.m3u   M3U with the one channel
  /guide.xml      XMLTV guide
  /live.ts        the stream (MPEG-TS); encoding runs only while someone watches
  /health         JSON status
  /               a page to watch the channels and see the station's status (web.py)

News is fetched all the time (it is cheap). Drawing and encoding start when
the first viewer connects and stop ``idle_seconds`` after the last one leaves.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
from datetime import UTC, datetime

from aiohttp import web

from .. import __version__, sound
from ..config import Config
from ..newsroom import Newsroom
from ..render import make_theme
from .encoder import Encoder
from .guide import ChannelInfo, channel_list, guide, playlist
from .playout import Playout
from .tsbuffer import TS, TsBuffer
from .web import add_routes

log = logging.getLogger(__name__)

# A viewer this far behind (bytes queued) is dropped rather than slowing everyone.
MAX_CLIENT_BACKLOG = 16 * 1024 * 1024


class Client:
    def __init__(self, peer: str) -> None:
        self.peer = peer
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.queued = 0
        self.skip = 0            # bytes to drop so a joiner continues on a packet boundary
        self.dropped = False

    def feed(self, chunk: bytes) -> None:
        if self.dropped:
            return
        if self.skip:
            if len(chunk) <= self.skip:
                self.skip -= len(chunk)
                return
            chunk = chunk[self.skip:]
            self.skip = 0
        self.queued += len(chunk)
        if self.queued > MAX_CLIENT_BACKLOG:
            log.warning("viewer %s is too far behind: dropping it", self.peer)
            self.dropped = True
            self.queue.put_nowait(None)
            return
        self.queue.put_nowait(chunk)

    def close(self) -> None:
        self.queue.put_nowait(None)


class Session:
    """One ffmpeg + playout, shared by everyone watching."""

    def __init__(self, channel: Channel) -> None:
        self.ch = channel
        cfg = channel.cfg
        self.fps = cfg.video.fps
        # Plus the frames the encoder holds back while the effects track runs ahead.
        self.lead = cfg.stream.lead_seconds + Encoder.AUDIO_LEAD_FRAMES / self.fps
        self.encoder = Encoder(cfg)
        self.playout = Playout(cfg, channel.newsroom, datetime.now(UTC), channel.theme)
        self.tsbuf = TsBuffer(self.lead, cfg.video.gop_seconds)
        self.t0 = time.monotonic()
        self.frames = 0
        self.lead_after: float | None = None
        self.tasks: list[asyncio.Task] = []
        self.thread: threading.Thread | None = None
        self.stopping = False

    async def start(self) -> None:
        await self.encoder.start()
        loop = asyncio.get_running_loop()
        self.thread = threading.Thread(target=self._render, args=(loop,), name="render", daemon=True)
        self.thread.start()
        self.tasks = [asyncio.create_task(self._read())]
        log.info("%s: session start: %dx%d %d fps, %s, %d music tracks, %.0f s lead", self.ch.info.name,
                 self.ch.cfg.video.width, self.ch.cfg.video.height, self.fps, self.ch.cfg.video.encoder,
                 self.encoder.tracks, self.lead)

    def _render(self, loop: asyncio.AbstractEventLoop) -> None:
        """The render thread: draw frames and feed ffmpeg, ``lead`` seconds ahead of the clock."""
        reason = "render loop ended"
        try:
            while not self.stopping:
                ahead = self.frames / self.fps - (time.monotonic() - self.t0)
                if ahead >= self.lead:
                    if self.lead_after is None:
                        self.lead_after = time.monotonic() - self.t0
                        log.info("%.0f s ahead after %.2f s", self.lead, self.lead_after)
                    time.sleep(min(1 / self.fps, ahead - self.lead + 0.001))
                    continue
                frame = self.playout.next_frame()
                self.encoder.write_blocking(frame, self.playout.next_audio())
                self.frames += 1
        except OSError as err:
            reason = f"encoder input closed ({err.strerror or err})"
        except Exception:
            log.exception("render loop failed")
            reason = "render loop failed"
        finally:
            if not self.stopping:
                loop.call_soon_threadsafe(lambda: asyncio.create_task(self.ch.stop_session(reason)))

    async def _read(self) -> None:
        try:
            while chunk := await self.encoder.read():
                for client in list(self.ch.clients):
                    client.feed(chunk)
                self.tsbuf.record(chunk, time.monotonic())
        except Exception:
            log.exception("reading the encoder failed")
        finally:
            if not self.stopping:
                code = self.encoder.proc.returncode if self.encoder.proc else None
                asyncio.create_task(self.ch.stop_session(f"ffmpeg exited ({code})"))

    async def stop(self) -> None:
        self.stopping = True
        for t in self.tasks:
            t.cancel()
        await self.encoder.stop()     # closes the pipe: a blocked write in the thread fails
        if self.thread:
            await asyncio.to_thread(self.thread.join, 5)


class Channel:
    def __init__(self, cfg: Config, newsroom: Newsroom, info: ChannelInfo) -> None:
        self.cfg = cfg
        self.info = info
        self.newsroom = newsroom
        self.theme = make_theme(cfg, info.theme, info.name)
        if hasattr(self.theme, "warm"):
            self.theme.warm()
        sound.sting(cfg.breaking.sound, getattr(self.theme, "kind", "studio"))   # synthesize it now
        self.clients: set[Client] = set()
        self.session: Session | None = None
        self.idle_handle: asyncio.TimerHandle | None = None
        self._lock = asyncio.Lock()
        self.stats = {"sessions": 0, "last_start": None, "last_stop": None, "last_stop_reason": None}

    async def ensure_session(self) -> None:
        async with self._lock:
            if self.session:
                return
            s = Session(self)
            self.session = s
            self.stats["sessions"] += 1
            self.stats["last_start"] = datetime.now(UTC).isoformat()
            try:
                await s.start()
            except Exception:
                self.session = None
                raise

    async def stop_session(self, reason: str) -> None:
        async with self._lock:
            s = self.session
            if not s:
                return
            self.session = None
            if self.idle_handle:
                self.idle_handle.cancel()
                self.idle_handle = None
            await s.stop()
            for c in list(self.clients):
                c.close()
            self.stats["last_stop"] = datetime.now(UTC).isoformat()
            self.stats["last_stop_reason"] = reason
            log.info("%s: session stop: %s (%.0f s of video)", self.info.name, reason, s.frames / s.fps)

    def client_left(self, client: Client) -> None:
        self.clients.discard(client)
        log.info("%s: viewer left (%d watching)", self.info.name, len(self.clients))
        if not self.clients and self.session and not self.idle_handle:
            idle = self.cfg.stream.idle_seconds
            self.idle_handle = asyncio.get_running_loop().call_later(
                idle, lambda: asyncio.create_task(self._idle_stop()))

    async def _idle_stop(self) -> None:
        self.idle_handle = None
        if not self.clients:
            await self.stop_session(f"idle {self.cfg.stream.idle_seconds:.0f} s")

    # --- HTTP handlers ---

    async def live(self, request: web.Request) -> web.StreamResponse:
        resp = web.StreamResponse(headers={"Content-Type": "video/mp2t", "Cache-Control": "no-cache"})
        await resp.prepare(request)          # headers out now: players wait on them
        if request.method == "HEAD":
            return resp
        client = Client(request.remote or "?")
        if self.idle_handle:
            self.idle_handle.cancel()
            self.idle_handle = None
        s = self.session
        if s and s.tsbuf:
            # Joining a running session: the head start, then live from the next packet.
            head = s.tsbuf.head_start(time.monotonic())
            client.queue.put_nowait(head)
            client.skip = (TS - s.tsbuf.partial) % TS
            log.info("head start for a joining viewer: %d KB", len(head) // 1024)
        self.clients.add(client)
        log.info("%s: viewer %s connected (%d watching)", self.info.name, client.peer, len(self.clients))
        try:
            await self.ensure_session()
            while (chunk := await client.queue.get()) is not None:
                client.queued -= len(chunk)
                await resp.write(chunk)
        except (ConnectionResetError, ConnectionError, asyncio.CancelledError):
            pass
        except Exception:
            log.exception("streaming to %s failed", client.peer)
        finally:
            self.client_left(client)
        with contextlib.suppress(Exception):
            await resp.write_eof()
        return resp

    def status(self) -> dict:
        s = self.session
        return {
            "name": self.info.name, "number": self.info.number, "theme": self.info.theme,
            "running": bool(s),
            "viewers": len(self.clients),
            "on_air": s.playout.on_air if s else None,
            "seconds_ahead": round(s.frames / s.fps - (time.monotonic() - s.t0), 2) if s else None,
            "lead_reached_after": round(s.lead_after, 2) if s and s.lead_after else None,
            **self.stats,
        }


class Station:
    """Every channel, sharing one newsroom (one fetch feeds them all)."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.newsroom = Newsroom(cfg)
        self.channels = {info.id: Channel(cfg, self.newsroom, info) for info in channel_list(cfg)}
        self.main = next(iter(self.channels.values()))

    async def live_main(self, request: web.Request) -> web.StreamResponse:
        return await self.main.live(request)

    async def live_by_id(self, request: web.Request) -> web.StreamResponse:
        ch = self.channels.get(request.match_info["id"])
        if ch is None:
            raise web.HTTPNotFound()
        return await ch.live(request)

    async def playlist(self, request: web.Request) -> web.Response:
        host = request.headers.get("Host") or f"localhost:{self.cfg.stream.port}"
        return web.Response(text=playlist(self.cfg, host), content_type="audio/x-mpegurl")

    async def guide(self, request: web.Request) -> web.Response:
        return web.Response(text=guide(self.cfg, datetime.now(UTC)), content_type="application/xml")

    async def health(self, request: web.Request) -> web.Response:
        room = self.newsroom
        rd = room.rundown
        return web.json_response({
            "version": __version__,
            "last_refresh": room.last_refresh.isoformat() if room.last_refresh else None,
            "refresh_error": room.last_error,
            "stories": len(rd.clusters) if rd else 0,
            "feeds_failing": [f["name"] + " " + f["url"] for f in room.feed_status() if f["error"]],
            "channels": [ch.status() for ch in self.channels.values()],
        })


def make_app(cfg: Config) -> web.Application:
    st = Station(cfg)
    app = web.Application()
    app["station"] = st
    app.router.add_get("/live.ts", st.live_main)          # GET also answers HEAD
    app.router.add_get("/live/{id}.ts", st.live_by_id)
    app.router.add_get("/playlist.m3u", st.playlist)
    app.router.add_get("/guide.xml", st.guide)
    app.router.add_get("/health", st.health)
    add_routes(app, st)

    async def background(app: web.Application):
        task = asyncio.create_task(st.newsroom.run())
        yield
        task.cancel()
        for ch in st.channels.values():
            await ch.stop_session("shutting down")

    app.cleanup_ctx.append(background)
    return app


def serve(cfg: Config) -> int:
    log.info("anchorless %s on port %d: %s", __version__, cfg.stream.port,
             ", ".join(f"{c.number} {c.name} ({c.theme})" for c in channel_list(cfg)))
    web.run_app(make_app(cfg), host=cfg.stream.host, port=cfg.stream.port, access_log=None,
                print=None, handle_signals=True)
    return 0
