"""``anchorless preview``: a short MP4 of the channel, made with the real playout and encoder."""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from ..config import Config
from ..newsroom import Newsroom
from .encoder import Encoder
from .playout import Playout


async def write_preview(cfg: Config, out: Path, seconds: float, breaking: bool) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    room = Newsroom(cfg)
    rundown = await room.refresh()
    now = datetime.now(UTC)
    if breaking and not rundown.empty:
        # Pretend the top story just broke, to see the alert.
        top = rundown.segments[0].clusters[0]
        room.raise_alert(top, now)
        room.add_breaking_tag(top, now)
    enc = Encoder(cfg, output=str(out), fmt="mp4", duration=seconds)
    await enc.start()
    play = Playout(cfg, room, now)
    frames = round(seconds * cfg.video.fps)
    t = time.perf_counter()

    def produce() -> None:
        for _ in range(frames):
            frame = play.next_frame()
            enc.write_blocking(frame, play.next_audio())

    try:
        await asyncio.to_thread(produce)
    except OSError:
        code = await enc.finish()
        print(f"ffmpeg stopped early (exit {code}); see its messages above", file=sys.stderr)
        return 1
    code = await enc.finish()
    took = time.perf_counter() - t
    print(f"{out}: {seconds:.0f} s of video in {took:.1f} s ({seconds / took:.1f}x real time), "
          f"{enc.tracks} music tracks, ffmpeg exit {code}")
    return 0 if code == 0 else 1
