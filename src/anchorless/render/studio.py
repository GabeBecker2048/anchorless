"""The Studio theme: an empty pixel-art news set. The news plays on the big screen
behind the desk. Nobody is at the desk, hence the name.

The set is drawn at a quarter of the output's area (427x240 for 854x480) and
scaled up 2x with hard edges, so every "pixel" is a 2x2 block. Text is drawn at
full resolution with pixel fonts, so headlines stay readable on a TV.

Things that stand on the floor are drawn in 2:1 isometric (depth runs up and to
the right); things on the back wall are flat. The window and the wall lighting
follow the local time of day.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from datetime import datetime
from functools import cached_property, lru_cache
from importlib.resources import files

from PIL import Image, ImageDraw, ImageFont

from ..config import Config
from ..models import Cluster
from .pages import ago, outlets_line
from .theme import wrap

FONT_DIR = files("anchorless") / "fonts"


@lru_cache(maxsize=64)
def pfont(name: str, size: int, weight: str | None = None) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT_DIR / f"{name}.ttf"), size)
    if weight:
        f.set_variation_by_name(weight)
    return f


Color = tuple[int, int, int]

# A small, saturated palette, like an old console's.
INK = (14, 14, 30)
BEZEL = (28, 28, 40)
BEZEL_HI = (70, 72, 96)
POLE = (40, 40, 56)
SCREEN_TOP = (20, 52, 150)
SCREEN_BOTTOM = (10, 26, 86)
DESK_TOP = (214, 140, 86)
DESK_TOP_HI = (238, 176, 118)
DESK_FRONT = (166, 92, 58)
DESK_SIDE = (120, 62, 42)
DESK_EDGE = (86, 42, 30)
GOLD = (255, 206, 84)
RED = (232, 52, 74)
RED_DARK = (140, 22, 44)
CYAN = (96, 222, 238)
WHITE = (244, 244, 252)
SOFT = (196, 210, 248)
MUTED = (130, 146, 200)
CHAIR = (96, 56, 140)
CHAIR_HI = (138, 92, 190)
CHAIR_TOP = (156, 112, 206)
CHAIR_DARK = (60, 34, 92)
GREEN = (88, 186, 96)
GREEN_HI = (140, 220, 120)
GREEN_DARK = (46, 120, 66)
POT = (190, 96, 64)
POT_SIDE = (140, 64, 44)
POT_TOP = (92, 60, 40)
WOOD = (92, 58, 44)
WOOD_SIDE = (66, 40, 32)
WOOD_TOP = (120, 80, 60)
WATER = (34, 112, 156)
WATER_SIDE = (24, 80, 120)
WATER_TOP = (90, 180, 210)
GLASS = (150, 224, 240)
SAND = (214, 190, 130)
COFFEE = (96, 58, 36)


# --- time of day ---------------------------------------------------------------

@dataclass(frozen=True)
class Lighting:
    sky_top: Color
    sky_bottom: Color
    wall_top: Color
    wall_bottom: Color
    stripe: Color
    floor_a: Color
    floor_b: Color
    building: Color
    cone: float          # spotlight cone strength (alpha)
    lit: float           # share of office windows lit
    stars: float
    sun: float           # 0 = none, 1 = sun, -1 = moon
    sun_y: float         # 0 = top of the window, 1 = horizon
    sun_color: Color


NIGHT = Lighting((6, 6, 28), (34, 22, 78), (18, 22, 54), (38, 46, 100), (48, 58, 124), (60, 46, 98),
                 (46, 34, 78), (16, 14, 40), 26, 0.45, 1.0, -1, 0.25, (230, 230, 210))
DAWN = Lighting((96, 96, 176), (255, 164, 120), (34, 40, 90), (72, 70, 128), (86, 90, 152), (84, 66, 118),
                (66, 50, 98), (62, 44, 92), 16, 0.25, 0.0, 1, 0.8, (255, 190, 110))
DAY = Lighting((84, 168, 240), (196, 232, 255), (50, 70, 140), (92, 112, 182), (112, 132, 198), (100, 84, 146),
               (80, 66, 124), (78, 96, 150), 6, 0.0, 0.0, 1, 0.2, (255, 244, 170))
DUSK = Lighting((58, 38, 120), (255, 118, 88), (38, 32, 86), (84, 58, 120), (102, 76, 148), (80, 58, 110),
                (62, 44, 90), (40, 26, 64), 18, 0.35, 0.15, 1, 0.85, (255, 120, 80))

# (local hour, lighting); colors blend between neighbours.
TIMELINE = [(0, NIGHT), (5.25, NIGHT), (6.5, DAWN), (8.5, DAY), (16.75, DAY), (18.5, DUSK), (20, NIGHT),
            (24, NIGHT)]


def _mix(a, b, t: float):
    if isinstance(a, tuple):
        return tuple(round(x + (y - x) * t) for x, y in zip(a, b, strict=True))
    return a + (b - a) * t


def lighting_at(hour: float) -> Lighting:
    hour %= 24
    for (h0, a), (h1, b) in zip(TIMELINE, TIMELINE[1:], strict=False):
        if h0 <= hour <= h1:
            t = (hour - h0) / (h1 - h0) if h1 > h0 else 0
            # The moon and the sun don't blend: one swaps for the other halfway.
            sun = a.sun if t < 0.5 else b.sun
            vals = {f.name: _mix(getattr(a, f.name), getattr(b, f.name), t) for f in fields(Lighting)}
            vals["sun"] = sun
            return Lighting(**vals)
    return NIGHT


# --- drawing helpers -----------------------------------------------------------

def _box(d: ImageDraw.ImageDraw, x0: float, y0: float, x1: float, y1: float, fill, outline=None) -> None:
    d.rectangle([x0, y0, x1, y1], fill=fill, outline=outline)


def iso_box(d: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, depth: int,
            front: Color, side: Color, top: Color, outline: Color | None = INK) -> None:
    """A box in 2:1 isometric: the front face is flat; depth runs up and to the right."""
    ox, oy = 2 * depth, -depth
    d.polygon([(x + w, y), (x + w + ox, y + oy), (x + w + ox, y + h + oy), (x + w, y + h)], fill=side,
              outline=outline)
    d.polygon([(x, y), (x + w, y), (x + w + ox, y + oy), (x + ox, y + oy)], fill=top, outline=outline)
    d.rectangle([x, y, x + w, y + h], fill=front, outline=outline)


def _dither_gradient(size: tuple[int, int], top, bottom, steps: int = 6) -> Image.Image:
    """A banded gradient with a 2x2 ordered dither between bands, like 16-bit art."""
    w, h = size
    cols = [tuple(round(top[c] + (bottom[c] - top[c]) * i / (steps - 1)) for c in range(3)) for i in range(steps)]
    band = h / (steps - 1)
    # Each row is one of two patterns: build them once, paste them.
    img = Image.new("RGB", size)
    for y in range(h):
        pos = y / band
        i = min(int(pos), steps - 2)
        frac = pos - i
        row = Image.new("RGB", (w, 1))
        rp = row.load()
        for x in range(min(w, 2)):
            threshold = (0.25, 0.75, 1.0, 0.5)[x + 2 * (y % 2)]
            rp[x, 0] = cols[i + 1] if frac > threshold - 0.125 else cols[i]
        if w > 2:
            pair = row.crop((0, 0, 2, 1))
            for x in range(0, w, 2):
                row.paste(pair, (x, 0))
        img.paste(row, (0, y))
    return img


# --- the theme -------------------------------------------------------------------

class StudioTheme:
    """Same interface as ClassicTheme, so the playout can use either."""

    SCALE = 2
    FLOOR_Y = 168
    DESK = (120, 300, 176, 212, 12)          # x0, x1, top, bottom, depth
    TANK = (340, 166, 50, 30, 10)            # x, y, w, h, depth (the glass box)

    def __init__(self, cfg: Config, channel_name: str | None = None) -> None:
        self.cfg = cfg
        self.channel_name = (channel_name or cfg.channel.name).upper()
        self.w = cfg.video.width
        self.h = cfg.video.height
        self.s = self.h / 480          # text scale relative to 480 lines
        self.k = self.SCALE * self.s
        self.lw = round(self.w / self.k)
        self.lh = round(self.h / self.k)
        self.screen = (70, 8, 357, 126)        # outer bezel (logical)
        self.inner = (75, 13, 352, 121)
        self.crawl_top = 216
        self.crawl_y = self.L(self.crawl_top + 2)
        self.crawl_h = self.h - self.crawl_y
        self.crawl_label_w = self.L(66)
        self.crawl_rect = (self.L(66), self.crawl_y, self.w - self.L(66), self.h - self.crawl_y)
        self.clock_box = tuple(self.L(v) for v in (10, 68, 61, 97))
        self._set_cache: dict[int, Image.Image] = {}

    def warm(self) -> None:
        """Draw the expensive, cached parts now, not when the first viewer arrives."""
        _ = self.background(datetime.now(self.cfg.tz)), self.front_big, self._scan
        self._screen_bg(False)
        self._screen_bg(True)

    def L(self, v: float) -> int:
        """Logical to output pixels."""
        return round(v * self.k)

    def px(self, v: float) -> int:
        return round(v * self.s)

    def _up(self, img: Image.Image) -> Image.Image:
        return img.resize((round(img.width * self.k), round(img.height * self.k)), Image.NEAREST)

    # --- the back of the set (changes with the time of day) ---

    def background(self, now: datetime) -> Image.Image:
        local = now.astimezone(self.cfg.tz)
        quarter = local.hour * 4 + local.minute // 15         # redrawn every 15 minutes
        img = self._set_cache.get(quarter)
        if img is None:
            img = self._draw_back(lighting_at(quarter / 4))
            self._set_cache = {quarter: img}
        return img

    def _draw_back(self, lt: Lighting) -> Image.Image:
        lw, lh, fy = self.lw, self.lh, self.FLOOR_Y
        img = _dither_gradient((lw, lh), lt.wall_top, lt.wall_bottom, steps=5)
        d = ImageDraw.Draw(img)

        # Wall panels and the skirting board.
        for x in range(0, lw, 36):
            _box(d, x, 0, x + 1, fy - 1, lt.stripe)
        _box(d, 0, fy - 6, lw, fy - 1, _mix(lt.wall_top, INK, 0.3))
        _box(d, 0, fy - 7, lw, fy - 7, lt.stripe)

        # Isometric checker floor.
        fpx = img.load()
        for y in range(fy, lh):
            for x in range(lw):
                u = (x / 2 + (y - fy)) // 10
                v = (x / 2 - (y - fy)) // 10
                fpx[x, y] = lt.floor_a if (u + v) % 2 == 0 else lt.floor_b
        _box(d, 0, fy, lw, fy, _mix(lt.floor_a, WHITE, 0.2))

        # The window on the city, stage left.
        self._draw_window(img, lt)
        d = ImageDraw.Draw(img)

        # Ceiling truss and spotlights with their light cones.
        _box(d, 0, 0, lw, 3, (40, 42, 58))
        for x in range(0, lw, 8):
            d.line([(x, 0), (x + 4, 3)], fill=(64, 66, 86))
        cones = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
        cd = ImageDraw.Draw(cones)
        for lx in (22, lw - 30):
            cd.polygon([(lx + 1, 12), (lx + 7, 12), (lx + 30, fy + 22), (lx - 22, fy + 22)],
                       fill=(255, 230, 160, round(lt.cone)))
        img = Image.alpha_composite(img.convert("RGBA"), cones).convert("RGB")
        d = ImageDraw.Draw(img)
        for lx in (22, lw - 30):
            _box(d, lx, 4, lx + 8, 10, (54, 56, 72))
            _box(d, lx + 1, 11, lx + 7, 12, GOLD)

        # The big screen's bezel.
        x0, y0, x1, y1 = self.screen
        _box(d, x0 - 1, y0 - 1, x1 + 1, y1 + 1, INK)
        _box(d, x0, y0, x1, y1, BEZEL)
        _box(d, x0, y0, x1, y0, BEZEL_HI)
        _box(d, x0, y0, x0, y1, BEZEL_HI)
        _box(d, (x0 + x1) // 2 - 3, y1 - 3, (x0 + x1) // 2 + 3, y1 - 2, CYAN)

        # Side monitors on poles, with isometric feet.
        for mx in (8, lw - 62):
            _box(d, mx + 25, 98, mx + 28, fy + 4, POLE)
            _box(d, mx + 25, 98, mx + 25, fy + 4, BEZEL_HI)
            iso_box(d, mx + 16, fy + 4, 18, 2, 3, POLE, (28, 28, 40), BEZEL_HI)
            _box(d, mx - 1, 65, mx + 55, 99, INK)
            _box(d, mx, 66, mx + 54, 98, BEZEL)
            _box(d, mx + 2, 68, mx + 52, 96, (8, 12, 30))

        # The ON AIR sign's box (its lettering is lit in _compose).
        _box(d, lw - 60, 22, lw - 14, 36, INK)

        # The crawl band.
        _box(d, 0, self.crawl_top, lw, lh, INK)
        _box(d, 0, self.crawl_top, lw, self.crawl_top + 1, GOLD)
        _box(d, 0, self.crawl_top + 2, 65, lh, GOLD)
        return self._up(img)

    def _draw_window(self, img: Image.Image, lt: Lighting) -> None:
        d = ImageDraw.Draw(img)
        wx, wy, ww, wh = 10, 17, 51, 39
        _box(d, wx - 1, wy - 1, wx + ww, wy + wh, INK)
        sky = _dither_gradient((ww, wh), lt.sky_top, lt.sky_bottom, steps=4)
        sd = ImageDraw.Draw(sky)
        if lt.stars > 0.3:
            for sx, sy in ((5, 3), (18, 6), (33, 2), (46, 8), (26, 11), (40, 4), (11, 9)):
                sd.point((sx, sy), fill=_mix(lt.sky_top, WHITE, lt.stars))
        if lt.sun:
            cx, cy = 38, round(2 + lt.sun_y * (wh - 14))
            r = 3 if lt.sun > 0 else 2
            sd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=lt.sun_color)
            if lt.sun < 0:   # a crescent: bite out of the moon
                sd.ellipse([cx - r + 1, cy - r - 1, cx + r + 1, cy + r - 1], fill=_mix(lt.sky_top, lt.sky_bottom, 0.2))
        for bx, bw, bh in ((0, 8, 22), (7, 6, 30), (13, 9, 18), (22, 7, 26), (29, 10, 14), (38, 6, 33), (44, 7, 20)):
            sd.rectangle([bx, wh - bh, bx + bw - 1, wh - 1], fill=lt.building)
            for yy in range(wh - bh + 2, wh - 2, 3):
                for xx in range(bx + 1, bx + bw - 1, 2):
                    seed = (xx * 7 + yy * 13) % 20
                    if seed < lt.lit * 20:
                        sd.point((xx, yy), fill=GOLD)
                    elif lt.lit < 0.1 and seed < 6:
                        sd.point((xx, yy), fill=_mix(lt.building, lt.sky_bottom, 0.5))
        img.paste(sky, (wx, wy))
        _box(d, wx + ww // 2, wy, wx + ww // 2, wy + wh - 1, INK)     # mullions
        _box(d, wx, wy + wh // 2, wx + ww - 1, wy + wh // 2, INK)
        _box(d, wx - 2, wy + wh, wx + ww + 1, wy + wh + 1, (60, 62, 84))   # sill

    # --- what stands in front of the screen (never changes) ---

    @cached_property
    def front(self) -> Image.Image:
        lw, lh = self.lw, self.lh
        img = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        cx = lw // 2

        # The empty chair: a rounded office-chair back, then the armrests in front of it.
        # Centred on the middle of the desk's top (which sits right of the front face,
        # because depth runs up and to the right), not on the screen.
        cx = cx + 5
        back = [cx - 17, 132, cx + 17, 176]
        d.rounded_rectangle([back[0] + 5, back[1] - 3, back[2] + 5, back[3] - 3], radius=9,
                            fill=CHAIR_DARK, outline=INK)                              # its thickness
        d.rounded_rectangle(back, radius=9, fill=CHAIR, outline=INK)
        d.rounded_rectangle([back[0] + 2, back[1] + 4, back[0] + 4, back[3] - 8], radius=1,
                            fill=CHAIR_HI)                                              # lit edge
        for y0 in (138, 152):                                                           # cushion seams
            d.rounded_rectangle([cx - 11, y0, cx + 11, y0 + 11], radius=4, outline=CHAIR_DARK)
        for ax in (cx - 25, cx + 15):                                                   # armrests
            _box(d, ax + 3, 161, ax + 6, 176, INK)                                      # post
            _box(d, ax + 4, 161, ax + 5, 176, (70, 70, 90))
            iso_box(d, ax, 157, 10, 4, 4, CHAIR_HI, CHAIR_DARK, CHAIR_TOP)             # pad

        cx = lw // 2
        # The desk.
        dx0, dx1, dtop, dbot, depth = self.DESK
        iso_box(d, dx0, dtop, dx1 - dx0, dbot - dtop, depth, DESK_FRONT, DESK_SIDE, DESK_TOP)
        d.line([(dx0 + 1, dtop - 1), (dx1, dtop - 1)], fill=DESK_TOP_HI)
        _box(d, dx0 + 1, dtop + 1, dx1 - 1, dtop + 3, GOLD)                 # brass trim
        _box(d, dx0 + 1, dbot - 4, dx1 - 1, dbot - 1, DESK_EDGE)
        _box(d, dx0 + 1, dbot - 6, dx1 - 1, dbot - 6, CYAN)                 # LED strip
        _box(d, cx - 44, dtop + 8, cx + 44, dbot - 9, INK)                  # logo panel
        _box(d, cx - 43, dtop + 9, cx + 43, dbot - 10, RED_DARK)
        _box(d, cx - 43, dtop + 9, cx + 43, dtop + 10, RED)

        # On the desk: the breaking-news beacon (off), papers, the mic, coffee.
        x0, y0, x1, y1 = self.BEACON
        iso_box(d, x0 - 2, y1, x1 - x0 + 4, 3, 2, (60, 60, 76), (40, 40, 52), (90, 90, 110))   # base
        d.rounded_rectangle([x0, y0, x1, y1 + 1], radius=4, fill=RED_DARK, outline=INK)       # dome
        _box(d, x0 + 2, y0 + 3, x0 + 3, y1 - 2, (190, 60, 80))                                 # glint
        for yy in range(y0 + 4, y1, 3):                                                        # fresnel ribs
            d.line([(x0 + 5, yy), (x1 - 2, yy)], fill=(110, 16, 34))
        iso_box(d, dx0 + 34, dtop - 4, 22, 2, 4, WHITE, (200, 200, 216), (230, 230, 244))
        iso_box(d, dx0 + 36, dtop - 7, 20, 2, 4, (236, 236, 248), (190, 190, 206), WHITE)
        _box(d, cx - 1, dtop - 18, cx + 1, dtop - 4, (60, 60, 76))          # mic stand
        _box(d, cx - 3, dtop - 23, cx + 3, dtop - 17, INK)
        _box(d, cx - 2, dtop - 22, cx + 2, dtop - 18, (120, 120, 140))
        iso_box(d, cx - 6, dtop - 4, 12, 1, 3, (60, 60, 76), (40, 40, 52), (90, 90, 110))
        mx, my = self.MUG
        iso_box(d, mx, my, 10, 12, 3, WHITE, (196, 196, 214), COFFEE)         # the mug
        _box(d, mx + 1, my + 1, mx + 9, my + 1, (60, 36, 24))
        _box(d, mx + 2, my + 5, mx + 8, my + 6, RED)                          # stripe
        d.arc([mx - 5, my + 2, mx + 1, my + 9], 90, 270, fill=INK, width=2)  # handle

        # A potted plant, stage left.
        iso_box(d, 24, 190, 20, 18, 5, POT, POT_SIDE, POT_TOP)
        _box(d, 25, 191, 43, 192, (222, 132, 92))
        base = (39, 186)
        for lx, ly in ((39, 160), (30, 168), (48, 166), (24, 178), (54, 176), (36, 170), (44, 158)):
            d.line([base, (lx, ly)], fill=GREEN_DARK, width=2)
            _box(d, lx - 3, ly - 2, lx + 3, ly + 2, GREEN)
            _box(d, lx - 3, ly - 2, lx, ly, GREEN_HI)

        # The aquarium on its cabinet, stage right.
        x, y, w, h, dep = self.TANK
        iso_box(d, x, y + h, w, 16, dep, WOOD, WOOD_SIDE, WOOD_TOP)
        _box(d, x + 3, y + h + 4, x + w // 2 - 1, y + h + 13, WOOD_SIDE)       # cabinet doors
        _box(d, x + w // 2 + 1, y + h + 4, x + w - 3, y + h + 13, WOOD_SIDE)
        iso_box(d, x, y, w, h, dep, WATER, WATER_SIDE, WATER_TOP, outline=GLASS)
        _box(d, x + 1, y + h - 4, x + w - 1, y + h - 1, SAND)
        for px_, ph in ((x + 8, 12), (x + 11, 8), (x + 40, 14), (x + 43, 9)):     # weeds
            d.line([(px_, y + h - 4), (px_ + 1, y + h - 4 - ph)], fill=GREEN_DARK, width=1)
            d.point((px_ + 1, y + h - 4 - ph), fill=GREEN)
        _box(d, x + 24, y + h - 7, x + 30, y + h - 4, (120, 120, 130))           # a rock
        _box(d, x - 1, y - 2, x + w + 1, y, INK)                                 # lid
        d.line([(x + 1, y + 1), (x + w - 1, y + 1)], fill=_mix(WATER, WHITE, 0.4))
        return img

    MUG = (270, 163)
    BEACON = (134, 158, 145, 170)        # the dome on the desk: x0, y0, x1, y1 (logical)

    @cached_property
    def front_big(self) -> Image.Image:
        big = self._up(self.front)
        d = ImageDraw.Draw(big)
        d.fontmode = "1"
        lw = self.lw
        f = pfont("PressStart2P-Regular", self.px(16))
        d.text((self.L(lw // 2), self.L(194)), self.channel_name, font=f, fill=GOLD, anchor="mm")
        f = pfont("Silkscreen-Bold", self.px(16))
        d.text((self.L(33), self.L(self.crawl_top + 13)), self.cfg.theme.crawl_label.upper(), font=f,
               fill=INK, anchor="mm")
        return big

    # --- the screen ---

    def _screen_rect(self) -> tuple[int, int, int, int]:
        x0, y0, x1, y1 = self.inner
        return self.L(x0), self.L(y0), self.L(x1 + 1), self.L(y1 + 1)

    @lru_cache(maxsize=2)  # noqa: B019 - one theme per channel, lives as long as the process
    def _screen_bg(self, breaking: bool = False) -> Image.Image:
        x0, y0, x1, y1 = self._screen_rect()
        top, bottom = ((170, 20, 44), (70, 6, 20)) if breaking else (SCREEN_TOP, SCREEN_BOTTOM)
        small = _dither_gradient((round((x1 - x0) / self.k), round((y1 - y0) / self.k)), top, bottom, steps=4)
        return small.resize((x1 - x0, y1 - y0), Image.NEAREST)

    @cached_property
    def _scan(self) -> Image.Image:
        x0, y0, x1, y1 = self._screen_rect()
        over = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
        d = ImageDraw.Draw(over)
        step = max(2, round(self.k))
        for y in range(0, over.height, step * 2):
            d.rectangle([0, y, over.width, y + step - 1], fill=(0, 0, 0, 34))
        return over

    def _on_air(self, lit: bool) -> Image.Image:
        img = Image.new("RGB", (self.L(45), self.L(13)), (255, 60, 80) if lit else (60, 14, 24))
        d = ImageDraw.Draw(img)
        d.fontmode = "1"
        d.text((img.width // 2, img.height // 2), "ON AIR", font=pfont("Silkscreen-Bold", self.px(16)),
               fill=WHITE if lit else (110, 40, 52), anchor="mm")
        return img

    @cached_property
    def _on_air_lit(self) -> Image.Image:
        return self._on_air(True)

    @cached_property
    def _on_air_off(self) -> Image.Image:
        return self._on_air(False)

    def _compose(self, screen: Image.Image, now: datetime | None, label: str = "", red: bool = False,
                 on_air: bool = True) -> Image.Image:
        img = self.background(now or datetime.now(self.cfg.tz)).copy()
        x0, y0, _, _ = self._screen_rect()
        scr = Image.alpha_composite(screen.convert("RGBA"), self._scan).convert("RGB")
        img.paste(scr, (x0, y0))
        img.paste(self.front_big, (0, 0), self.front_big)
        img.paste(self._on_air_lit if on_air else self._on_air_off, (self.L(self.lw - 59), self.L(23)))
        if label:
            d = ImageDraw.Draw(img)
            d.fontmode = "1"
            mx = self.lw - 62
            for size in (16, 8):
                f = pfont("Silkscreen-Bold", self.px(size))
                lines, ok = wrap(label.upper(), f, self.L(48), 2)
                if ok:
                    break
            cy = self.L(82) - (len(lines) - 1) * self.px(9)
            for i, ln in enumerate(lines):
                d.text((self.L(mx + 27), cy + i * self.px(18)), ln, font=f, fill=RED if red else CYAN,
                       anchor="mm")
        return img

    def story_page(self, cluster: Cluster, segment: str, index: int, total: int, now: datetime,
                   breaking: bool = False) -> Image.Image:
        scr = self._screen_bg(breaking).copy()
        d = ImageDraw.Draw(scr)
        d.fontmode = "1"
        W, H = scr.size
        m = self.px(14)
        tab_f = pfont("Silkscreen-Bold", self.px(16))
        tab = "BREAKING NEWS" if breaking else segment.upper()
        tw = tab_f.getlength(tab)
        d.rectangle([0, 0, tw + 2 * m, self.px(26)], fill=GOLD if breaking else RED)
        d.text((m, self.px(13)), tab, font=tab_f, fill=INK if breaking else WHITE, anchor="lm")
        small = pfont("Silkscreen-Regular", self.px(16))
        right = ago(cluster.when, now)
        if total > 1 and not breaking:
            right = f"{index}/{total}  " + right
        d.text((W - m, self.px(13)), right, font=small, fill=SOFT, anchor="rm")

        y = self.px(36)
        story = cluster.lead
        hf = pfont("PixelifySans", self.px(28), "Bold")
        lines, ok = wrap(story.title, hf, W - 2 * m, 3)
        if not ok:
            hf = pfont("PixelifySans", self.px(22), "Bold")
            lines, _ = wrap(story.title, hf, W - 2 * m, 3)
        step = hf.size + self.px(4)
        for ln in lines:
            d.text((m + self.px(2), y + self.px(2)), ln, font=hf, fill=INK)
            d.text((m, y), ln, font=hf, fill=WHITE)
            y += step
        y += self.px(6)
        d.rectangle([m, y, m + self.px(40), y + self.px(3)], fill=GOLD)
        y += self.px(10)

        sf = pfont("VT323-Regular", self.px(22))
        bottom = H - self.px(28)
        room = max(0, int((bottom - y) // (sf.size + self.px(1))))
        if story.summary and room:
            slines, _ = wrap(story.summary, sf, W - 2 * m, room)
            for ln in slines:
                d.text((m, y), ln, font=sf, fill=SOFT)
                y += sf.size + self.px(1)
        d.text((m, H - self.px(12)), "SRC: " + outlets_line(cluster), font=small, fill=GOLD, anchor="lm")
        return self._compose(scr, now, "ALERT!" if breaking else segment, red=breaking)

    def intro_page(self, segment: str, clusters: list[Cluster], now: datetime | None = None) -> Image.Image:
        scr = self._screen_bg().copy()
        d = ImageDraw.Draw(scr)
        d.fontmode = "1"
        W, H = scr.size
        m = self.px(14)
        f = pfont("PressStart2P-Regular", self.px(32))
        lines, _ = wrap(segment.upper(), f, W - 2 * m, 1)
        d.text((m + self.px(3), self.px(22) + self.px(3)), lines[0], font=f, fill=INK)
        d.text((m, self.px(22)), lines[0], font=f, fill=GOLD)
        y = self.px(70)
        d.text((m, y), "COMING UP", font=pfont("Silkscreen-Bold", self.px(16)), fill=CYAN)
        y += self.px(26)
        nf = pfont("PressStart2P-Regular", self.px(16))
        hf = pfont("VT323-Regular", self.px(22))
        for i, c in enumerate(clusters[:4], 1):
            d.text((m, y + self.px(2)), f"{i}", font=nf, fill=RED)
            ln, _ = wrap(c.lead.title, hf, W - 2 * m - self.px(28), 1)
            d.text((m + self.px(26), y), ln[0], font=hf, fill=WHITE)
            y += self.px(26)
        return self._compose(scr, now, segment)

    def breaking_title(self, flash: bool, now: datetime | None = None) -> Image.Image:
        scr = self._screen_bg(breaking=True).copy()
        d = ImageDraw.Draw(scr)
        d.fontmode = "1"
        W, H = scr.size
        d.rectangle((0, H // 2 - self.px(40), W, H // 2 + self.px(40)), fill=GOLD if flash else WHITE)
        f = pfont("PressStart2P-Regular", self.px(32))
        d.text((W // 2 + self.px(3), H // 2 - self.px(11)), "BREAKING", font=f, fill=INK, anchor="mm")
        d.text((W // 2, H // 2 - self.px(14)), "BREAKING", font=f, fill=RED, anchor="mm")
        d.text((W // 2, H // 2 + self.px(22)), "NEWS", font=pfont("PressStart2P-Regular", self.px(24)),
               fill=INK, anchor="mm")
        return self._compose(scr, now, "ALERT!", red=True)

    def empty_page(self, now: datetime | None = None) -> Image.Image:
        scr = self._screen_bg().copy()
        d = ImageDraw.Draw(scr)
        d.fontmode = "1"
        W, H = scr.size
        bars = [(200, 200, 200), (200, 200, 40), (40, 200, 200), (40, 200, 40), (200, 40, 200),
                (200, 40, 40), (40, 40, 200)]
        bw = W / len(bars)
        for i, c in enumerate(bars):
            d.rectangle([round(i * bw), 0, round((i + 1) * bw), H], fill=c)
        d.rectangle([0, H // 2 - self.px(24), W, H // 2 + self.px(24)], fill=INK)
        d.text((W // 2, H // 2), "PLEASE STAND BY", font=pfont("PressStart2P-Regular", self.px(16)),
               fill=WHITE, anchor="mm")
        return self._compose(scr, now, "STAND BY", on_air=False)

    # --- the crawl ---

    def crawl_style(self) -> dict:
        return {"font": pfont("PixelifySans", self.px(22), "Medium"), "tag_font": pfont("Silkscreen-Bold", self.px(16)),
                "bg": INK, "text": WHITE, "sep": RED, "tag_bg": RED, "tag_text": WHITE, "crisp": True}

    # --- every frame ---

    def clock_key(self, now: datetime) -> str:
        local = now.astimezone(self.cfg.tz)
        return f"{local:%Y%m%d%H%M}{local.second % 2}"

    def clock(self, now: datetime) -> Image.Image:
        x0, y0, x1, y1 = self.clock_box
        img = Image.new("RGB", (x1 - x0, y1 - y0), (8, 12, 30))
        d = ImageDraw.Draw(img)
        d.fontmode = "1"
        local = now.astimezone(self.cfg.tz)
        f = pfont("PressStart2P-Regular", self.px(16))
        hour = local.strftime("%I").lstrip("0")
        colon = ":" if local.second % 2 == 0 else " "
        # Draw the parts separately so the digits don't shift when the colon blinks.
        cw = f.getlength(":")
        hw, mw = f.getlength(hour), f.getlength(f"{local:%M}")
        x = (img.width - (hw + cw + mw)) / 2
        cy = img.height // 2 - self.px(6)
        d.text((x, cy), hour, font=f, fill=GOLD, anchor="lm")
        d.text((x + hw, cy), colon, font=f, fill=GOLD, anchor="lm")
        d.text((x + hw + cw, cy), f"{local:%M}", font=f, fill=GOLD, anchor="lm")
        f2 = pfont("Silkscreen-Regular", self.px(16))
        d.text((img.width // 2, img.height // 2 + self.px(14)), f"{local:%p} {local:%a}".upper(), font=f2,
               fill=MUTED, anchor="mm")
        return img

    def overlay(self, canvas: Image.Image, frame: int, fps: int, alert: bool) -> Image.Image:
        """The living details, drawn over each frame: fish, steam, and the breaking-news alarm."""
        t = frame / fps
        self._fish(canvas, t)
        self._steam(canvas, t)
        if alert:
            canvas = self._alarm(canvas, t)
        return canvas

    def _fish(self, canvas: Image.Image, t: float) -> None:
        x, y, w, h, _ = self.TANK
        iw, ih = w - 2, h - 6
        layer = Image.new("RGBA", (iw, ih), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        # (speed px/s, row, color, phase): faint, as if seen through the glass.
        for speed, row, color, phase in ((6, 6, (255, 150, 60), 0.0), (4.5, 14, (255, 220, 90), 0.4),
                                         (8, 10, (120, 230, 250), 0.7)):
            span = iw - 6
            pos = (t * speed / span + phase) % 2
            right = pos < 1
            fx = round((pos if right else 2 - pos) * span) + 1
            fy = row + round(math.sin(t * 1.3 + phase * 6))
            a = 150
            d.rectangle([fx, fy, fx + 2, fy + 1], fill=(*color, a))
            tail = fx - 1 if right else fx + 3
            d.point((tail, fy), fill=(*color, a - 40))
            d.point((tail, fy + 1), fill=(*color, a - 40))
            d.point((fx + 2 if right else fx, fy), fill=(14, 14, 30, a))       # an eye
        for i in range(3):                                                     # bubbles
            by = ih - 1 - ((t * 5 + i * 7) % ih)
            d.point((w - 12 + (i % 2), by), fill=(220, 240, 255, 110))
        big = self._up(layer)
        canvas.paste(big, (self.L(x + 1), self.L(y + 2)), big)

    def _steam(self, canvas: Image.Image, t: float) -> None:
        mx, my = self.MUG
        w, h = 10, 14
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        for i in range(4):
            phase = (t * 0.7 + i / 4) % 1
            yy = round(h - 1 - phase * (h - 2))
            xx = round(4 + math.sin(phase * 7 + i * 1.7) * 2)
            a = round(200 * (1 - phase))
            d.point((xx, yy), fill=(235, 235, 245, a))
            d.point((xx + 1, yy - 1), fill=(235, 235, 245, a // 2))
        big = self._up(layer)
        canvas.paste(big, (self.L(mx + 1), self.L(my - h - 3)), big)

    @cached_property
    def _beam(self) -> Image.Image:
        return Image.new("RGB", (self.w, self.h), (255, 40, 60))

    @cached_property
    def _red(self) -> Image.Image:
        return Image.new("RGB", (self.w, self.h), (255, 0, 30))

    def _alarm(self, canvas: Image.Image, t: float) -> Image.Image:
        """The whole studio pulses red, the desk beacon spins, ON AIR flashes."""
        pulse = 0.5 + 0.5 * math.sin(t * 2 * math.pi * 1.5)
        canvas = Image.blend(canvas, self._red, 0.10 + 0.20 * pulse)
        # Two beams sweeping from the beacon on the desk (drawn as a mask, then pasted).
        x0, y0, x1, y1 = self.BEACON
        bx, by = (x0 + x1) / 2, y0 + 5
        mask = Image.new("L", (self.lw, self.lh), 0)
        md = ImageDraw.Draw(mask)
        ang = t * 2 * math.pi * 1.2
        for k in (0, math.pi):
            a, spread, far = ang + k, 0.22, 260
            md.polygon([(bx, by),
                        (bx + far * math.cos(a - spread), by + far * math.sin(a - spread) * 0.6),
                        (bx + far * math.cos(a + spread), by + far * math.sin(a + spread) * 0.6)], fill=70)
        big = self._up(mask)
        box = big.getbbox()
        if box:
            canvas.paste(self._beam.crop(box), box[:2], big.crop(box))
        # The lit dome, with a bright band where the lamp inside is pointing.
        d = ImageDraw.Draw(canvas)
        L = self.L
        d.rounded_rectangle([L(x0), L(y0), L(x1 + 1) - 1, L(y1 + 2) - 1], radius=L(4), fill=(255, 70, 90),
                            outline=INK, width=max(1, L(1) // 2))
        band = x0 + 2 + (math.cos(ang) * 0.5 + 0.5) * (x1 - x0 - 5)
        d.rectangle([L(band), L(y0 + 2), L(band + 2) - 1, L(y1 - 1) - 1], fill=(255, 230, 230))
        lit = int(t * 4) % 2 == 0
        canvas.paste(self._on_air_lit if lit else self._on_air_off, (L(self.lw - 59), L(23)))
        return canvas
