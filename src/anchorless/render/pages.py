"""The Classic theme: every full-screen page the channel shows.

All sizes are designed at 480 lines and scaled with the output height, so the
same layout works at 480p, 720p and 1080p (16:9).
"""

from __future__ import annotations

from datetime import datetime
from functools import cached_property

from PIL import Image, ImageDraw, ImageFont

from ..config import Config
from ..models import Cluster
from .theme import (
    DARK_PALETTE,
    PALETTE,
    draw_lines,
    draw_tracked,
    fit,
    font,
    gradient,
    stripes,
    tracked_width,
    wrap,
)


def ago(when: datetime | None, now: datetime) -> str:
    if when is None:
        return ""
    minutes = int((now - when).total_seconds() // 60)
    if minutes < 2:
        return "JUST IN"
    if minutes < 60:
        return f"{minutes} MIN AGO"
    hours = minutes // 60
    return f"{hours} HR AGO" if hours < 24 else f"{hours // 24} DAY{'S' if hours >= 48 else ''} AGO"


def outlets_line(cluster: Cluster, limit: int = 3) -> str:
    names = cluster.outlets
    shown = " · ".join(n.upper() for n in names[:limit])
    return shown + (f"  +{len(names) - limit} MORE" if len(names) > limit else "")


class ClassicTheme:
    kind = "classic"

    def __init__(self, cfg: Config, channel_name: str | None = None, dark: bool = False) -> None:
        self.cfg = cfg
        self.P = DARK_PALETTE if dark else PALETTE
        self.channel_name = (channel_name or cfg.channel.name).upper()
        self.w = cfg.video.width
        self.h = cfg.video.height
        self.s = self.h / 480

        S = self.px
        self.header_h = S(58)
        self.crawl_h = S(46)
        self.crawl_y = self.h - self.crawl_h
        self.body = (0, self.header_h, self.w, self.crawl_y)
        self.margin = S(34)
        self.logo_w = S(150)
        self.clock_box = (self.w - S(230), 0, self.w, self.header_h - S(3))
        self.crawl_label_w = S(132)
        self.crawl_rect = (self.crawl_label_w, self.crawl_y + S(2), self.w - self.crawl_label_w, self.crawl_h - S(2))

    def px(self, v: float) -> int:
        return round(v * self.s)

    # --- pieces drawn once ---

    def _header(self, label: str, logo: tuple | None = None, bar: tuple | None = None,
                top: tuple | None = None, bottom: tuple | None = None) -> Image.Image:
        P = self.P
        logo, bar = logo or P.red, bar or P.gold
        top, bottom = top or P.header_top, bottom or P.header_bottom
        S = self.px
        img = gradient((self.w, self.header_h), top, bottom)
        d = ImageDraw.Draw(img)
        d.rectangle([0, self.header_h - S(3), self.w, self.header_h], fill=bar)
        # The logo: a slanted block with the channel name.
        slant = S(18)
        d.polygon([(0, 0), (self.logo_w + slant, 0), (self.logo_w, self.header_h - S(3)),
                   (0, self.header_h - S(3))], fill=logo)
        f = font("cond-black", S(38))
        name = self.channel_name
        nw = f.getlength(name)
        while nw > self.logo_w - S(16) and f.size > S(18):
            f = font("cond-black", f.size - 2)
            nw = f.getlength(name)
        d.text(((self.logo_w - nw) / 2 + S(4), self._baseline(f, (self.header_h - S(3)) / 2)),
               name, font=f, fill=P.white, anchor="ls")
        if label:
            f = font("cond-bold", S(30))
            x = self.logo_w + slant + S(16)
            room = self.clock_box[0] - x - S(10)
            lines, _ = wrap(label.upper(), f, room, 1)
            d.text((x, self._baseline(f, (self.header_h - S(3)) / 2)), lines[0], font=f,
                   fill=P.white, anchor="ls")
        return img

    @cached_property
    def body_bg(self) -> Image.Image:
        P = self.P
        size = (self.w, self.crawl_y - self.header_h)
        return stripes(gradient(size, P.body_top, P.body_bottom), self.px(7), 9)

    @cached_property
    def breaking_bg(self) -> Image.Image:
        size = (self.w, self.crawl_y - self.header_h)
        return stripes(gradient(size, (170, 14, 36), (64, 2, 12)), self.px(7), 12)

    @cached_property
    def crawl_bg(self) -> Image.Image:
        P = self.P
        S = self.px
        img = Image.new("RGB", (self.w, self.crawl_h), P.crawl_bg)
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, self.w, S(2)], fill=P.gold)
        d.rectangle([0, S(2), self.crawl_label_w, self.crawl_h], fill=P.gold)
        f = font("cond-black", S(22))
        label = self.cfg.crawl.label.upper()
        lw = tracked_width(label, f, S(1))
        draw_tracked(d, ((self.crawl_label_w - lw) / 2, self._baseline(f, S(2) + (self.crawl_h - S(2)) / 2)
                         - f.getmetrics()[0]), label, f, P.navy, S(1))
        return img

    def _baseline(self, f: ImageFont.FreeTypeFont, center_y: float) -> float:
        """Baseline that centers capital letters on ``center_y``."""
        top, bottom = f.getbbox("H", anchor="ls")[1], 0
        return center_y + (bottom - top) / 2

    def _frame(self, header: Image.Image, body: Image.Image) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        img = Image.new("RGB", (self.w, self.h))
        img.paste(header, (0, 0))
        img.paste(body, (0, self.header_h))
        img.paste(self.crawl_bg, (0, self.crawl_y))
        return img, ImageDraw.Draw(img)

    # --- the pages ---

    def story_page(self, cluster: Cluster, segment: str, index: int, total: int, now: datetime,
                   breaking: bool = False) -> Image.Image:
        P = self.P
        S = self.px
        header = self._header(segment if not breaking else "BREAKING NEWS",
                              logo=P.red if not breaking else P.white,
                              bar=P.gold if not breaking else P.red)
        if breaking:
            hd = ImageDraw.Draw(header)
            f = font("cond-black", S(38))
            name = self.channel_name
            nw = f.getlength(name)
            hd.text(((self.logo_w - nw) / 2 + S(4), self._baseline(f, (self.header_h - S(3)) / 2)),
                    name, font=f, fill=P.red, anchor="ls")
        img, d = self._frame(header, self.breaking_bg if breaking else self.body_bg)
        story = cluster.lead
        x = self.margin
        width = self.w - 2 * self.margin
        y = self.header_h + S(22)

        # Kicker line: "STORY 2 OF 4" and how long ago.
        f = font("semibold", S(15))
        kicker = "DEVELOPING STORY" if breaking else (f"STORY {index} OF {total}" if total > 1 else "")
        if kicker:
            draw_tracked(d, (x, y), kicker, f, P.gold if not breaking else P.white, S(1.5))
        when = ago(cluster.when, now)
        if when:
            ww = tracked_width(when, f, S(1.5))
            draw_tracked(d, (self.w - self.margin - ww, y), when, f, P.soft, S(1.5))
        y += S(28)

        # The headline: as big as fits in three lines.
        hf, lines = fit(story.title, "cond-bold", [S(v) for v in (46, 42, 38, 34, 31, 28)], width, 3)
        y = draw_lines(d, (x, y), lines, hf, P.white, spacing=1.0, shadow=(0, 0, 0), offset=S(2))
        y += S(12)
        d.rectangle([x, y, x + S(64), y + S(4)], fill=P.gold if not breaking else P.white)
        y += S(18)

        # The summary fills what is left above the source line.
        bottom = self.crawl_y - S(46)
        if story.summary:
            for size in (21, 20, 19, 18):
                sf = font("regular", S(size))
                asc, desc = sf.getmetrics()
                max_lines = max(0, int((bottom - y) // ((asc + desc) * 1.25)))
                slines, ok = wrap(story.summary, sf, width, max_lines) if max_lines else ([], False)
                if ok:
                    break
            if slines:
                draw_lines(d, (x, y), slines, sf, P.soft, spacing=1.25)

        # Source credit, bottom left; story position pips, bottom right.
        y = self.crawl_y - S(34)
        f = font("semibold", S(15))
        xe = draw_tracked(d, (x, y), "SOURCE", f, P.gold if not breaking else P.white, S(1.5))
        d.text((xe + S(12), y), outlets_line(cluster), font=font("semibold", S(16)), fill=P.white)
        if total > 1 and not breaking:
            r = S(4)
            gap = S(14)
            px0 = self.w - self.margin - (total - 1) * gap
            for i in range(total):
                cx, cy = px0 + i * gap, y + S(9)
                fill = P.gold if i == index - 1 else P.dot
                d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)
        return img

    def intro_page(self, segment: str, clusters: list[Cluster], now: datetime | None = None) -> Image.Image:
        P = self.P
        S = self.px
        img, d = self._frame(self._header(""), self.body_bg)
        x = self.margin
        y = self.header_h + S(34)
        f = font("cond-black", S(72))
        lines, _ = wrap(segment.upper(), f, self.w - 2 * x, 1)
        d.text((x + S(3), y + S(3)), lines[0], font=f, fill=(0, 0, 0))
        d.text((x, y), lines[0], font=f, fill=P.white)
        y += f.getmetrics()[0] + S(14)
        d.rectangle([x, y, x + S(120), y + S(6)], fill=P.red)
        y += S(26)
        draw_tracked(d, (x, y), "COMING UP", font("semibold", S(15)), P.gold, S(1.5))
        y += S(30)
        hf = font("medium", S(21))
        nf = font("cond-black", S(20))
        box = S(28)
        for i, c in enumerate(clusters[:5], 1):
            d.rectangle([x, y, x + box, y + box], fill=P.gold)
            nw = nf.getlength(str(i))
            d.text((x + (box - nw) / 2, self._baseline(nf, y + box / 2)), str(i), font=nf,
                   fill=P.navy, anchor="ls")
            line, _ = wrap(c.lead.title, hf, self.w - 2 * x - box - S(14), 1)
            d.text((x + box + S(14), self._baseline(hf, y + box / 2)), line[0], font=hf,
                   fill=P.white, anchor="ls")
            y += box + S(14)
            if y > self.crawl_y - box - S(12):
                break
        return img

    def breaking_title(self, flash: bool, now: datetime | None = None) -> Image.Image:
        """The full-screen "BREAKING NEWS" card; ``flash`` swaps the colors."""
        P = self.P
        S = self.px
        header = self._header("", logo=P.white, bar=P.red)
        hd = ImageDraw.Draw(header)
        f = font("cond-black", S(38))
        name = self.channel_name
        nw = f.getlength(name)
        hd.text(((self.logo_w - nw) / 2 + S(4), self._baseline(f, (self.header_h - S(3)) / 2)),
                name, font=f, fill=P.red, anchor="ls")
        img, d = self._frame(header, self.breaking_bg)
        cy = (self.header_h + self.crawl_y) / 2
        band_h = S(120)
        band = (0, cy - band_h / 2, self.w, cy + band_h / 2)
        d.rectangle(band, fill=P.white if not flash else P.gold)
        d.rectangle([0, band[1] - S(5), self.w, band[1]], fill=P.gold if not flash else P.white)
        d.rectangle([0, band[3], self.w, band[3] + S(5)], fill=P.gold if not flash else P.white)
        f = font("cond-black", S(92))
        text = "BREAKING NEWS"
        tw = tracked_width(text, f, S(3))
        draw_tracked(d, ((self.w - tw) / 2, self._baseline(f, cy) - f.getmetrics()[0]), text, f, P.red, S(3))
        return img

    def empty_page(self, now: datetime | None = None) -> Image.Image:
        P = self.P
        S = self.px
        img, d = self._frame(self._header("STAND BY"), self.body_bg)
        cy = (self.header_h + self.crawl_y) / 2
        f = font("cond-bold", S(44))
        text = "GATHERING THE LATEST HEADLINES"
        d.text((self.w / 2, cy - S(8)), text, font=f, fill=P.white, anchor="ms")
        sf = font("medium", S(20))
        d.text((self.w / 2, cy + S(30)), "The newscast starts in a moment.", font=sf, fill=P.soft, anchor="ms")
        return img

    # --- the parts that change every frame ---

    def crawl_style(self) -> dict:
        P = self.P
        S = self.px
        return {"font": font("semibold", S(21)), "tag_font": font("cond-black", S(16)), "bg": P.crawl_bg,
                "text": P.white, "sep": P.red, "tag_bg": P.red, "tag_text": P.white}

    def clock_key(self, now: datetime) -> str:
        return f"{now.astimezone(self.cfg.tz):%Y%m%d%H%M}"

    def overlay(self, canvas: Image.Image, frame: int, fps: int, alert: bool) -> Image.Image:
        return canvas

    def clock(self, now: datetime) -> Image.Image:
        P = self.P
        S = self.px
        x0, y0, x1, y1 = self.clock_box
        img = gradient((x1 - x0, self.header_h), P.header_top, P.header_bottom).crop((0, 0, x1 - x0, y1 - y0))
        d = ImageDraw.Draw(img)
        local = now.astimezone(self.cfg.tz)
        hour = local.strftime("%I").lstrip("0")
        tf = font("cond-bold", S(30))
        time_text = f"{hour}:{local:%M}"
        ampm = local.strftime("%p")
        af = font("cond-semibold", S(18))
        base = self._baseline(tf, (y1 - y0) / 2)
        right = (x1 - x0) - S(18)
        aw = af.getlength(ampm)
        d.text((right - aw, base), ampm, font=af, fill=P.soft, anchor="ls")
        tw = tf.getlength(time_text)
        d.text((right - aw - S(5) - tw, base), time_text, font=tf, fill=P.white, anchor="ls")
        df = font("cond-semibold", S(18))
        date = f"{local:%a %b} {local.day}".upper()
        dw = df.getlength(date)
        d.text((right - aw - S(5) - tw - S(14) - dw, base), date, font=df, fill=P.muted, anchor="ls")
        return img
