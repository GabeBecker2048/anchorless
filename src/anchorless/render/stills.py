"""``anchorless render``: PNG stills of every page type, for reviewing a theme."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..config import Config
from ..newsroom import Newsroom
from ..stream.playout import Playout
from . import make_theme

log = logging.getLogger(__name__)


def _frame_at(cfg: Config, room: Newsroom, theme, start: datetime, seconds: float, breaking=None):
    """A real frame from the playout, ``seconds`` in (with the crawl, clock and animation)."""
    if breaking is not None:
        room.raise_alert(breaking, start)
    play = Playout(cfg, room, start, theme)
    frame = None
    for _ in range(max(1, round(seconds * cfg.video.fps))):
        frame = play.next_image()
    return frame.copy()


async def write_stills(cfg: Config, out: Path, theme_name: str | None = None) -> int:
    out.mkdir(parents=True, exist_ok=True)
    room = Newsroom(cfg)
    rundown = await room.refresh()
    now = datetime.now(UTC)
    theme = make_theme(cfg, theme_name)
    written = []

    def save(name: str, img) -> None:
        path = out / f"{name}.png"
        img.save(path)
        written.append(path)

    if rundown.empty:
        log.warning("no stories: only the stand-by page")
        save("stand-by", _frame_at(cfg, room, theme, now, 1))
    else:
        intro = cfg.rundown.intro_seconds
        save("1-segment-intro", _frame_at(cfg, room, theme, now, max(1, intro - 1)))
        save("2-story", _frame_at(cfg, room, theme, now, intro + 2))
        big = rundown.segments[0].clusters[0]
        room.add_breaking_tag(big, now)
        save("3-breaking-flash", _frame_at(cfg, room, theme, now, 1.6, breaking=big))
        save("4-breaking-story", _frame_at(cfg, room, theme, now, 4.6, breaking=big))
        room.breaking_tags.clear()
    save("5-stand-by", theme.empty_page(now))
    # The studio at four times of day.
    if hasattr(theme, "background"):
        tz = cfg.tz
        local = now.astimezone(tz)
        for label, hour in (("night", 2), ("morning", 7), ("day", 13), ("dusk", 18.5)):
            t = local.replace(hour=int(hour), minute=int((hour % 1) * 60), second=0) + timedelta(0)
            seg = rundown.segments[0] if not rundown.empty else None
            img = (theme.story_page(seg.clusters[0], seg.name, 1, len(seg.clusters), t) if seg
                   else theme.empty_page(t))
            save(f"6-time-{label}", img)
    for p in written:
        print(p)
    return 0
