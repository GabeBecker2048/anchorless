"""The playout: what is on screen at every frame, as raw RGB for the encoder.

Pages are drawn once when they come up; every frame then only pastes the page,
the clock and a window of the crawl. Frames carry their own timeline (the
first frame is ``start``), so they can be produced ahead of real time.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from PIL import Image, ImageDraw

from ..config import Config
from ..models import Cluster, Rundown
from ..render.crawl import Crawl
from ..render.pages import ClassicTheme
from ..render.theme import PALETTE as P


class NewsFeed(Protocol):
    """What the playout needs from the newsroom."""

    rundown: Rundown | None
    version: int

    def take_breaking(self, now: datetime) -> Cluster | None: ...
    def crawl_items(self, now: datetime) -> list[tuple[str, bool]]: ...


@dataclass
class Shot:
    frames: int
    fade_in: bool = True

    def image(self, i: int) -> Image.Image:
        raise NotImplementedError


@dataclass
class Still(Shot):
    img: Image.Image | None = None

    def image(self, i: int) -> Image.Image:
        assert self.img is not None
        return self.img


@dataclass
class Flash(Shot):
    """Two images alternating every ``period`` frames."""

    a: Image.Image | None = None
    b: Image.Image | None = None
    period: int = 6

    def image(self, i: int) -> Image.Image:
        return self.a if (i // self.period) % 2 == 0 else self.b


@dataclass
class Wipe(Shot):
    """``dst`` sweeps in over ``src`` from the left, behind a red bar."""

    src: Image.Image | None = None
    dst: Image.Image | None = None
    bar: int = 16

    def image(self, i: int) -> Image.Image:
        assert self.src is not None and self.dst is not None
        w, h = self.dst.size
        x = round(w * (i + 1) / self.frames)
        img = self.src.copy()
        img.paste(self.dst.crop((0, 0, x, h)), (0, 0))
        if x < w:
            ImageDraw.Draw(img).rectangle([x, 0, x + self.bar, h], fill=P.red)
        return img


class Playout:
    def __init__(self, cfg: Config, news: NewsFeed, start: datetime, theme: ClassicTheme | None = None) -> None:
        self.cfg = cfg
        self.news = news
        self.theme = theme or ClassicTheme(cfg)
        self.fps = cfg.video.fps
        self.start = start
        self.frame_no = 0
        self.canvas = Image.new("RGB", (self.theme.w, self.theme.h))
        self._shots = self._program()
        self._shot: Shot | None = None
        self._shot_i = 0
        self._last: Image.Image | None = None
        self._from: Image.Image | None = None
        self._clock_key: str | None = None
        self._clock_img: Image.Image | None = None
        self.crawl = Crawl(self.theme, news.crawl_items(start), self.fps)
        self._crawl_version = news.version
        self._crawl_now = False
        self.on_air: str = ""          # what is showing, for /health and logs
        self._just_broke: set[str] = set()

    def seconds(self, s: float) -> int:
        return max(1, round(s * self.fps))

    def now(self) -> datetime:
        """The time the current frame will be on screen."""
        return self.start + timedelta(seconds=self.frame_no / self.fps)

    # --- the program: an endless sequence of shots ---

    def _program(self) -> Iterator[Shot]:
        r = self.cfg.rundown
        t = self.theme
        seg_i = 0
        while True:
            rundown = self.news.rundown
            if rundown is None or rundown.empty:
                self.on_air = "stand by"
                yield Still(self.seconds(r.page_seconds / 2), img=t.empty_page())
                continue
            # The rundown is re-read at every segment boundary, so new stories
            # join there and never in the middle of a page.
            if seg_i >= len(rundown.segments):
                seg_i = 0
                self._just_broke.clear()      # a new loop: everything may run again
            seg = rundown.segments[seg_i]
            seg_i += 1
            yield from self._breaking()
            # A story that just aired as breaking news is not repeated in this loop.
            clusters = [c for c in seg.clusters if c.key not in self._just_broke]
            if not clusters:
                continue
            if r.intro_seconds:
                self.on_air = f"{seg.name}: intro"
                yield Still(self.seconds(r.intro_seconds), img=t.intro_page(seg.name, clusters))
            for i, cluster in enumerate(clusters, 1):
                yield from self._breaking()
                self.on_air = f"{seg.name}: {cluster.lead.title}"
                yield Still(self.seconds(r.page_seconds),
                            img=t.story_page(cluster, seg.name, i, len(clusters), self.now()))

    def _breaking(self) -> Iterator[Shot]:
        cluster = self.news.take_breaking(self.now())
        if cluster is None:
            return
        self._just_broke.add(cluster.key)
        t = self.theme
        self._crawl_now = True
        self.on_air = f"BREAKING: {cluster.lead.title}"
        title = t.breaking_title(flash=False)
        if self._last is not None:
            yield Wipe(self.seconds(0.5), fade_in=False, src=self._last, dst=title, bar=t.px(16))
        yield Flash(self.seconds(3), fade_in=False, a=title, b=t.breaking_title(flash=True),
                    period=self.seconds(0.25))
        yield Wipe(self.seconds(0.4), fade_in=False, src=title,
                   dst=(page := t.story_page(cluster, "BREAKING NEWS", 1, 1, self.now(), breaking=True)),
                   bar=t.px(16))
        yield Still(self.seconds(self.cfg.rundown.page_seconds * 1.5), fade_in=False, img=page)

    # --- frames ---

    def next_image(self) -> Image.Image:
        if self._shot is None or self._shot_i >= self._shot.frames:
            self._from = self._last
            self._shot = next(self._shots)
            self._shot_i = 0
        shot, i = self._shot, self._shot_i
        img = shot.image(i)
        fade = self.seconds(self.cfg.rundown.transition_seconds) if self.cfg.rundown.transition_seconds else 0
        if shot.fade_in and self._from is not None and i < fade:
            img = Image.blend(self._from, img, (i + 1) / (fade + 1))
        self._shot_i += 1
        self._last = shot.image(i) if shot.fade_in else img

        c = self.canvas
        c.paste(img, (0, 0))
        now = self.now()
        key = f"{now.astimezone(self.cfg.tz):%Y%m%d%H%M}"
        if key != self._clock_key:
            self._clock_key = key
            self._clock_img = self.theme.clock(now)
        x0, y0, _, _ = self.theme.clock_box
        c.paste(self._clock_img, (x0, y0))

        wrapped = self.crawl.advance()
        if (self._crawl_now or (wrapped and self.news.version != self._crawl_version)):
            items = self.news.crawl_items(now)
            if items != self.crawl.items:
                self.crawl = Crawl(self.theme, items, self.fps).continue_from(self.crawl)
            self._crawl_version = self.news.version
            self._crawl_now = False
        c.paste(self.crawl.window(), (self.theme.crawl_label_w, self.theme.crawl_y + self.theme.px(2)))
        self.frame_no += 1
        return c

    def next_frame(self) -> bytes:
        """The next frame as raw rgb24."""
        return self.next_image().tobytes()
