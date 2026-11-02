"""The headline crawl along the bottom of the screen.

The whole crawl is drawn once into one long strip; each frame only crops a
window out of it, so moving it costs almost nothing.
"""

from __future__ import annotations

from typing import Any

from PIL import Image, ImageDraw


class Crawl:
    def __init__(self, theme: Any, items: list[tuple[str, bool]], fps: int) -> None:
        """``items``: (headline, carries the BREAKING tag)."""
        self.theme = theme
        self.style = theme.crawl_style()
        _, _, self.view_w, self.h = theme.crawl_rect
        # Whole pixels per frame, so the text never shimmers between pixels.
        self.step = max(1, round(theme.cfg.theme.crawl_speed * theme.s / fps))
        self.items = list(items)
        self.strip, self.loop_w = self._draw(self.items or [("Stay tuned for the latest headlines", False)])
        self.offset = 0
        self.lead_in: Image.Image | None = None

    def continue_from(self, old: Crawl) -> Crawl:
        """Start where ``old`` is now: its visible text scrolls off, this crawl scrolls in."""
        self.lead_in = old.window()
        self.offset = -self.view_w
        return self

    def _draw(self, items: list[tuple[str, bool]]) -> tuple[Image.Image, int]:
        S = self.theme.px
        st = self.style
        f = st["font"]
        tag_f = st["tag_font"]
        gap = S(22)
        sep = S(8)
        # Measure one loop of the crawl.
        pieces = []
        x = 0
        for text, breaking in items:
            tag_w = (tag_f.getlength("BREAKING") + S(14) + S(10)) if breaking else 0
            w = tag_w + f.getlength(text)
            pieces.append((x, text, breaking))
            x += int(w) + gap + sep + gap
        loop_w = max(x, 1)
        # Repeat until it is wider than loop + view, so a crop never wraps.
        copies = 1 + -(-self.view_w // loop_w)
        strip = Image.new("RGB", (loop_w * (copies + 1), self.h), st["bg"])
        d = ImageDraw.Draw(strip)
        if st.get("crisp"):
            d.fontmode = "1"
        cy = self.h / 2
        base = cy + (-f.getbbox("H", anchor="ls")[1]) / 2
        tag_base = cy + (-tag_f.getbbox("H", anchor="ls")[1]) / 2
        for c in range(copies + 1):
            for px, text, breaking in pieces:
                x = c * loop_w + px
                if breaking:
                    tw = tag_f.getlength("BREAKING") + S(14)
                    d.rectangle([x, cy - S(11), x + tw, cy + S(11)], fill=st["tag_bg"])
                    d.text((x + S(7), tag_base), "BREAKING", font=tag_f, fill=st["tag_text"], anchor="ls")
                    x += tw + S(10)
                d.text((x, base), text, font=f, fill=st["text"], anchor="ls")
                x += f.getlength(text) + gap
                d.rectangle([x, cy - sep / 2, x + sep, cy + sep / 2], fill=st["sep"])
        return strip, loop_w

    def advance(self) -> bool:
        """Move one frame. True when the crawl just wrapped (a good moment to swap it)."""
        self.offset += self.step
        if self.offset >= self.loop_w:
            self.offset -= self.loop_w
            return True
        return False

    def window(self) -> Image.Image:
        if self.offset >= 0 or self.lead_in is None:
            return self.strip.crop((self.offset, 0, self.offset + self.view_w, self.h))
        shown = self.offset + self.view_w          # pixels of the old window already gone
        img = Image.new("RGB", (self.view_w, self.h), self.style["bg"])
        img.paste(self.lead_in.crop((shown, 0, self.view_w, self.h)), (0, 0))
        if shown > 0:
            img.paste(self.strip.crop((0, 0, shown, self.h)), (self.view_w - shown, 0))
        return img
