"""Drawing helpers shared by the pages: fonts, colors, text fitting, backgrounds."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files

from PIL import Image, ImageDraw, ImageFont

Color = tuple[int, int, int]

FONT_DIR = files("anchorless") / "fonts"
FONTS = {
    "regular": "Barlow-Regular.ttf",
    "medium": "Barlow-Medium.ttf",
    "semibold": "Barlow-SemiBold.ttf",
    "bold": "Barlow-Bold.ttf",
    "cond-semibold": "BarlowCondensed-SemiBold.ttf",
    "cond-bold": "BarlowCondensed-Bold.ttf",
    "cond-black": "BarlowCondensed-ExtraBold.ttf",
}


@lru_cache(maxsize=128)
def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / FONTS[name]), max(6, size))


@dataclass(frozen=True)
class Palette:
    header_top: Color = (14, 32, 78)
    header_bottom: Color = (6, 16, 44)
    body_top: Color = (24, 74, 166)
    body_bottom: Color = (7, 28, 82)
    crawl_bg: Color = (5, 14, 38)
    red: Color = (204, 18, 48)
    red_dark: Color = (96, 4, 18)
    gold: Color = (244, 184, 52)
    white: Color = (255, 255, 255)
    soft: Color = (216, 228, 250)
    muted: Color = (150, 174, 218)
    navy: Color = (8, 22, 58)
    dot: Color = (70, 104, 170)            # the story-progress dots not lit


PALETTE = Palette()

# Classic dark: the same pages in charcoal and near-black instead of blue.
DARK_PALETTE = Palette(
    header_top=(30, 31, 37), header_bottom=(14, 14, 18),
    body_top=(34, 36, 44), body_bottom=(10, 10, 14),
    crawl_bg=(5, 5, 7), white=(242, 242, 246), soft=(198, 202, 214),
    muted=(140, 146, 162), navy=(14, 14, 18), dot=(74, 76, 90),
)


def gradient(size: tuple[int, int], top: Color, bottom: Color) -> Image.Image:
    w, h = size
    mask = Image.linear_gradient("L").resize((w, h))
    return Image.composite(Image.new("RGB", size, bottom), Image.new("RGB", size, top), mask)


def stripes(img: Image.Image, spacing: int, alpha: int) -> Image.Image:
    """Faint diagonal stripes, the 90s cable-news texture."""
    w, h = img.size
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for x in range(-h, w, spacing):
        d.line([(x, h), (x + h, 0)], fill=(255, 255, 255, alpha), width=max(1, spacing // 4))
    out = img.convert("RGBA")
    out.alpha_composite(layer)
    return out.convert("RGB")


def text_width(text: str, f: ImageFont.FreeTypeFont) -> float:
    return f.getlength(text)


def wrap(text: str, f: ImageFont.FreeTypeFont, width: float, max_lines: int) -> tuple[list[str], bool]:
    """Word-wrap to ``width``; returns (lines, everything_fit). Overflow ends in an ellipsis."""
    words = text.split()
    lines: list[str] = []
    line = ""
    for i, word in enumerate(words):
        trial = f"{line} {word}".strip()
        if f.getlength(trial) <= width or not line:
            line = trial
            continue
        lines.append(line)
        line = word
        if len(lines) == max_lines:
            rest = " ".join([line, *words[i + 1:]])
            lines[-1] = _ellipsize(f"{lines[-1]} {rest}", f, width)
            return lines, False
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _ellipsize(lines[-1] + " …", f, width)
        return lines, False
    # A single word wider than the line still has to be cut.
    fits = all(f.getlength(ln) <= width for ln in lines)
    if not fits:
        lines = [ln if f.getlength(ln) <= width else _ellipsize(ln, f, width) for ln in lines]
    return lines, fits


def _ellipsize(text: str, f: ImageFont.FreeTypeFont, width: float) -> str:
    if f.getlength(text) <= width:
        return text
    words = text.split()
    while words:
        candidate = " ".join(words).rstrip(",;:.-–—") + "…"
        if f.getlength(candidate) <= width:
            return candidate
        words.pop()
    out = text
    while out and f.getlength(out + "…") > width:
        out = out[:-1]
    return out + "…"


def fit(text: str, face: str, sizes: list[int], width: float, max_lines: int
        ) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """The largest size at which ``text`` fits in ``max_lines``; the smallest (cut) otherwise."""
    lines: list[str] = []
    f = font(face, sizes[-1])
    for size in sizes:
        f = font(face, size)
        lines, ok = wrap(text, f, width, max_lines)
        if ok:
            return f, lines
    return f, lines


def draw_lines(d: ImageDraw.ImageDraw, xy: tuple[float, float], lines: list[str],
               f: ImageFont.FreeTypeFont, fill: Color, spacing: float = 1.15,
               shadow: Color | None = None, offset: int = 2) -> float:
    """Draw lines top-down from ``xy``; returns the y just below the last line."""
    x, y = xy
    ascent, descent = f.getmetrics()
    step = (ascent + descent) * spacing
    for line in lines:
        if shadow:
            d.text((x + offset, y + offset), line, font=f, fill=shadow)
        d.text((x, y), line, font=f, fill=fill)
        y += step
    return y - step + ascent + descent if lines else y


def tracked_width(text: str, f: ImageFont.FreeTypeFont, tracking: float) -> float:
    return f.getlength(text) + tracking * max(0, len(text) - 1)


def draw_tracked(d: ImageDraw.ImageDraw, xy: tuple[float, float], text: str,
                 f: ImageFont.FreeTypeFont, fill: Color, tracking: float) -> float:
    """Letter-spaced text (small caps labels); returns the x after the last letter."""
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=f, fill=fill)
        x += f.getlength(ch) + tracking
    return x - tracking
