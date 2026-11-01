"""``anchorless render``: PNG stills of every page type, for reviewing a theme."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from ..config import Config
from ..newsroom import Newsroom
from ..stream.playout import Playout
from .crawl import Crawl
from .pages import ClassicTheme

log = logging.getLogger(__name__)


def _with_overlays(theme: ClassicTheme, page, items, now: datetime, fps: int):
    img = page.copy()
    x0, y0, _, _ = theme.clock_box
    img.paste(theme.clock(now), (x0, y0))
    crawl = Crawl(theme, items, fps)
    for _ in range(round(fps * 1.5)):   # a little way in, like a real frame
        crawl.advance()
    img.paste(crawl.window(), (theme.crawl_label_w, theme.crawl_y + theme.px(2)))
    return img


async def write_stills(cfg: Config, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    room = Newsroom(cfg)
    rundown = await room.refresh()
    now = datetime.now(UTC)
    theme = ClassicTheme(cfg)
    items = room.crawl_items(now)
    fps = cfg.video.fps
    written = []

    def save(name: str, img) -> None:
        path = out / f"{name}.png"
        img.save(path)
        written.append(path)

    if rundown.empty:
        log.warning("no stories: only the stand-by page")
    else:
        seg = rundown.segments[0]
        save("1-segment-intro", _with_overlays(theme, theme.intro_page(seg.name, seg.clusters), items, now, fps))
        save("2-story", _with_overlays(theme, theme.story_page(seg.clusters[0], seg.name, 1,
                                                                 len(seg.clusters), now), items, now, fps))
        # The longest headline in the rundown, to check that text fitting works.
        longest = max(rundown.clusters, key=lambda c: len(c.lead.title) + len(c.lead.summary))
        save("3-story-long-headline", _with_overlays(theme, theme.story_page(longest, "WORLD", 2, 3, now),
                                                     items, now, fps))
        big = rundown.segments[0].clusters[0]
        tagged = [(big.lead.title, True)] + [i for i in items if i[0] != big.lead.title]
        save("4-breaking-title", _with_overlays(theme, theme.breaking_title(False), tagged, now, fps))
        save("5-breaking-story", _with_overlays(theme, theme.story_page(big, "BREAKING NEWS", 1, 1, now,
                                                                         breaking=True), tagged, now, fps))
    save("6-stand-by", _with_overlays(theme, theme.empty_page(), [], now, fps))

    # One frame straight out of the playout, to prove the real path renders.
    play = Playout(cfg, room, now, theme)
    for _ in range(fps * 2):
        frame = play.next_image()
    save("7-playout-frame", frame.copy())

    for p in written:
        print(p)
    return 0
