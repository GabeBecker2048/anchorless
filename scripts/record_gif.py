"""Re-record the README's Studio GIF (docs/studio.gif) from the real playout.

    uv run python scripts/record_gif.py              # writes docs/studio.gif
    uv run python scripts/record_gif.py -o out/x.gif --speed 2

The stories and outlets are made up (no feeds are fetched), and the clock is fixed,
so every run draws the same frames. It plays a TOP STORIES intro and two stories,
then a breaking-news alert, sped up. Needs ffmpeg on the PATH.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from anchorless.config import Config
from anchorless.models import Cluster, Rundown, Segment, Story
from anchorless.stream.playout import Playout

ROOT = Path(__file__).resolve().parent.parent
TZ = "America/Chicago"
# A Friday afternoon: daylight through the window.
START = datetime(2026, 11, 6, 14, 20, tzinfo=ZoneInfo(TZ))

# (headline, summary, minutes old, outlets). All made up.
TOP_STORIES = [
    ("Researchers map deep-sea vents teeming with previously unknown species",
     "A six-week expedition catalogued more than 40 animals never seen before, "
     "living around hot springs two miles below the surface.",
     58, ["Metro Wire", "Daily Ledger", "Global Post"]),
    ("Glaciologists report record snowpack across the northern range",
     "Reservoirs downstream are expected to fill for the first time in a decade, "
     "easing water limits in three states.",
     44, ["World Desk", "Global Post"]),
    ("Small-business lending rises for the third straight quarter",
     "Banks approved more loans to shops and restaurants than at any time since 2019.",
     71, ["Daily Ledger", "Metro Wire"]),
    ("Regional rail line sets ridership record as new express service opens",
     "Trains between the two largest cities now take under an hour.",
     90, ["Metro Wire"]),
]
BREAKING = ("Astronomers confirm a new comet will be visible to the naked eye next week",
            "It should be brightest low in the western sky just after sunset, "
            "observatories said.",
            15, ["World Desk", "Metro Wire", "Daily Ledger", "Global Post"])


def _cluster(i: int, title: str, summary: str, minutes: int, outlets: list[str]) -> Cluster:
    when = START - timedelta(minutes=minutes)
    stories = [Story(key=f"s{i}-{n}", title=title, summary=summary, outlet=o, url=f"https://example.com/{i}/{n}",
                     published=when, scope="national", category="general") for n, o in enumerate(outlets)]
    return Cluster(stories=stories)


class FakeNews:
    """The newsroom as the playout sees it: a fixed rundown, and one alert at ``alert_at``."""

    def __init__(self, alert_at: datetime) -> None:
        self.top = [_cluster(i, *s) for i, s in enumerate(TOP_STORIES)]
        self.breaking = _cluster(99, *BREAKING)
        self.rundown = Rundown(segments=[Segment("TOP STORIES", self.top)], built_at=START)
        self.version = 1
        self.alert_at = alert_at

    def next_alert(self, now: datetime, after: int) -> tuple[int, Cluster] | None:
        return (1, self.breaking) if now >= self.alert_at and after < 1 else None

    def crawl_items(self, now: datetime) -> list[tuple[str, bool]]:
        items = [(c.lead.title, False) for c in self.top]
        if now >= self.alert_at:
            items.insert(0, (self.breaking.lead.title, True))
        return items


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-o", "--out", default=str(ROOT / "docs" / "studio.gif"))
    ap.add_argument("--speed", type=float, default=2.5, help="how much faster than real time (default 2.5)")
    ap.add_argument("--fps", type=int, default=15, help="GIF frame rate (default 15)")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config(channel={"theme": "studio", "show_on": "both", "channel_number": 2, "timezone": TZ},
                     source=[{"name": "Metro Wire", "url": "https://example.com/rss"}],
                     data={"dir": tmp}, video={"fps": 24})
        r = cfg.rundown
        # The alert lands just after the second story comes up, so it breaks in after it.
        alert_at = START + timedelta(seconds=r.intro_seconds + r.page_seconds + 1)
        # Record until the breaking story has been up a while (the alarm has calmed down).
        breaks_in = r.intro_seconds + 2 * r.page_seconds
        seconds = breaks_in + 0.5 + 3 + 0.4 + 3 + 5
        play = Playout(cfg, FakeNews(alert_at), START.astimezone(ZoneInfo("UTC")))

        step = cfg.video.fps * args.speed / args.fps     # playout frames per GIF frame
        total = round(seconds * cfg.video.fps)
        w, h = cfg.video.width, cfg.video.height
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        ff = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
             "-r", str(args.fps), "-i", "-",
             "-vf", "split[a][b];[a]palettegen=stats_mode=diff[p];"
                    "[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle",
             "-loop", "0", str(out)],
            stdin=subprocess.PIPE)
        assert ff.stdin
        nxt, kept = 0.0, 0
        for i in range(total):
            img = play.next_image()
            if i >= nxt:
                ff.stdin.write(img.convert("RGB").tobytes())
                nxt += step
                kept += 1
        ff.stdin.close()
        if ff.wait() != 0:
            print("ffmpeg failed", file=sys.stderr)
            return 1
    print(f"{out}: {kept} frames, {kept / args.fps:.1f} s ({seconds:.0f} s of playout at {args.speed}x), "
          f"{out.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
