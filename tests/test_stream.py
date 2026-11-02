from datetime import UTC, datetime, timedelta

import pytest

from anchorless.config import Config
from anchorless.models import Rundown
from anchorless.pipeline import all_clusters, build_rundown
from anchorless.stream.encoder import ffmpeg_args
from anchorless.stream.guide import guide, playlist
from anchorless.stream.playout import Playout
from anchorless.stream.tsbuffer import TS, TsBuffer, is_keyframe

from .conftest import NOW


def _packet(pid: int, key: bool = False) -> bytes:
    p = bytearray(TS)
    p[0] = 0x47
    p[1] = (0x40 if key else 0) | (pid >> 8)
    p[2] = pid & 0xFF
    if key:
        p[3] = 0x30
        p[4] = 7
        p[5] = 0x40
    return bytes(p)


def test_keyframe_detection():
    assert is_keyframe(_packet(0x100, key=True))
    assert not is_keyframe(_packet(0x100))
    assert not is_keyframe(_packet(0x101, key=True))


def test_head_start_begins_at_a_keyframe_with_tables():
    buf = TsBuffer(lead_seconds=10, gop_seconds=2)
    pat, pmt = _packet(0), _packet(0x1000)
    for second in range(20):
        chunk = pat + pmt + _packet(0x100, key=True) + _packet(0x100) + _packet(0x101)
        buf.record(chunk[:300], float(second))   # split mid-packet on purpose
        buf.record(chunk[300:], float(second))
    head = buf.head_start(20.0)
    assert head[:TS] == pat and head[TS:2 * TS] == pmt
    assert is_keyframe(head[2 * TS:3 * TS])
    assert len(head) % TS == 0
    # Roughly lead seconds of video: 10-11 keyframes.
    keys = sum(is_keyframe(head[i:i + TS]) for i in range(0, len(head), TS))
    assert 10 <= keys <= 12


class FakeNews:
    def __init__(self, rundown):
        self.rundown = rundown
        self.version = 1
        self.queue = []

    def next_alert(self, now, after):
        for seq, c in enumerate(self.queue, 1):
            if seq > after:
                return seq, c
        return None

    def crawl_items(self, now):
        return [(c.lead.title, False) for c in self.rundown.clusters] if self.rundown else []


@pytest.mark.parametrize("theme", ["studio", "classic"])
def test_playout_frames(stories, cfg, theme):
    cfg.theme.name = theme
    cfg.rundown.page_seconds = 3
    cfg.rundown.intro_seconds = 1
    cfg.video.fps = 4
    rundown = build_rundown(all_clusters(stories, cfg, NOW), cfg, NOW)
    news = FakeNews(rundown)
    news.queue.append(rundown.clusters[0])
    play = Playout(cfg, news, NOW)
    size = cfg.video.width * cfg.video.height * 3
    seen = set()
    for _ in range(4 * 30):
        assert len(play.next_frame()) == size
        seen.add(play.on_air.split(":")[0])
    assert "BREAKING" in seen and "TOP STORIES" in seen


@pytest.mark.parametrize("theme", ["studio", "classic"])
def test_playout_empty_rundown(theme):
    cfg = Config()
    cfg.theme.name = theme
    cfg.video.fps = 2
    play = Playout(cfg, FakeNews(Rundown(segments=[], built_at=NOW)), NOW)
    play.next_frame()
    assert play.on_air == "stand by"


def test_guide_and_playlist_with_an_extra_channel():
    from anchorless.config import ExtraChannelConfig

    cfg = Config(extra_channel=[ExtraChannelConfig(name="NEWS CLASSIC", number=97, id="x.classic")])
    text = guide(cfg, datetime(2026, 11, 1, 12, tzinfo=UTC))
    # DST ends on 2026-11-01 in Chicago: the first day is 25 hours long.
    assert 'start="20261101000000 -0500" stop="20261102000000 -0600"' in text
    assert text.count("<channel ") == 2 and text.count("<programme ") == 6
    m3u = playlist(cfg, "host:9798").splitlines()
    assert 'tvg-chno="98"' in m3u[1] and m3u[2] == "http://host:9798/live.ts"
    assert 'tvg-chno="97"' in m3u[3] and m3u[4] == "http://host:9798/live/x.classic.ts"


def test_ffmpeg_args():
    cfg = Config()
    args = ffmpeg_args(cfg, None)
    assert "libx264" in args and "repeat-headers=1" in args and args[-1] == "pipe:1"
    cfg.video.encoder = "vaapi"
    args = ffmpeg_args(cfg, None)
    assert "h264_vaapi" in args and "-vaapi_device" in args
    assert any("hwupload" in a for a in args)
    cfg.video.vaapi_convert = "gpu"
    args = ffmpeg_args(cfg, None)
    assert "bgr0" in args and any("scale_vaapi" in a for a in args)


def test_gpu_convert_frames_are_bgrx(stories, cfg):
    cfg.video.encoder = "vaapi"
    cfg.video.vaapi_convert = "gpu"
    cfg.video.fps = 2
    rundown = build_rundown(all_clusters(stories, cfg, NOW), cfg, NOW)
    frame = Playout(cfg, FakeNews(rundown), NOW).next_frame()
    assert len(frame) == cfg.video.width * cfg.video.height * 4


def test_breaking_story_not_repeated_but_no_dead_loop(stories, cfg):
    from anchorless.config import SegmentConfig

    cfg.video.fps = 2
    cfg.rundown.page_seconds = 3
    cfg.rundown.segment = [SegmentConfig(name="ONLY", stories=1)]
    rundown = build_rundown(all_clusters(stories, cfg, NOW), cfg, NOW)
    news = FakeNews(rundown)
    news.queue.append(rundown.clusters[0])
    play = Playout(cfg, news, NOW)
    shown = []
    for _ in range(2 * 60):
        play.next_frame()
        shown.append(play.on_air)
    # The breaking alert, then (after a loop) the story again: never a hang.
    assert shown[0].startswith("BREAKING") and any(s.startswith("ONLY") for s in shown)


def test_studio_lighting_follows_the_clock():
    from anchorless.render.studio import DAY, NIGHT, lighting_at

    assert lighting_at(2) == NIGHT
    assert lighting_at(12) == DAY
    dawn = lighting_at(6.0)
    assert dawn.sky_top != NIGHT.sky_top and dawn.sky_top != DAY.sky_top


def test_sun_and_moon_move_smoothly_and_never_swap_mid_sky():
    from anchorless.render.studio import ARC_HORIZON, sky_bodies

    prev = {b.kind: b for b in sky_bodies(-1 / 60)}    # 23:59 the evening before
    for minute in range(24 * 60 + 1):
        bodies = {b.kind: b for b in sky_bodies(minute / 60)}
        assert len(bodies) <= 1, f"sun and moon both up at minute {minute}"
        for kind, b in bodies.items():
            if kind in prev:   # a pixel or two a minute at most (fastest right at the rooftops)
                assert abs(b.x - prev[kind].x) <= 2 and abs(b.y - prev[kind].y) <= 2
            else:              # it comes up from behind the rooftops, not out of thin air
                assert b.y >= ARC_HORIZON[0] - 1
        for kind, b in prev.items():
            if kind not in bodies:   # and goes down behind them
                assert b.y >= ARC_HORIZON[0] - 1
        prev = bodies
    assert {b.kind for b in sky_bodies(12)} == {"sun"} and {b.kind for b in sky_bodies(0)} == {"moon"}


def test_studio_clock_blinks():
    from anchorless.render.studio import StudioTheme

    t = StudioTheme(Config())
    a, b = NOW, NOW + timedelta(seconds=1)
    assert t.clock_key(a) != t.clock_key(b)
    assert t.clock(a).tobytes() != t.clock(b).tobytes()


def test_alerts_reach_every_channel(cfg, stories):
    from anchorless.newsroom import Newsroom
    from anchorless.store import Store

    room = Newsroom(cfg, Store(":memory:"))
    rundown = build_rundown(all_clusters(stories, cfg, NOW), cfg, NOW)
    room.rundown = rundown
    room.raise_alert(rundown.clusters[0], NOW)
    a = Playout(cfg, room, NOW)
    b = Playout(cfg, room, NOW)
    a.next_frame()
    b.next_frame()
    assert a.on_air.startswith("BREAKING") and b.on_air.startswith("BREAKING")
    # Stale after 15 minutes.
    c = Playout(cfg, room, NOW + timedelta(minutes=20))
    c.next_frame()
    assert not c.on_air.startswith("BREAKING")


def test_stings_synthesize():
    from anchorless import sound

    for name in sound.STINGS:
        pcm = sound.sting(name)
        assert pcm and len(pcm) % 4 == 0 and 1.5 < len(pcm) / 4 / sound.RATE < 4
    assert sound.sting("none") is None
    assert sound.sting("/no/such/file.mp3") is None


@pytest.mark.parametrize("fps", [24, 25, 30, 60])
def test_effects_track_stays_in_step_with_video(stories, cfg, fps):
    from anchorless import sound

    cfg.video.fps = fps
    rundown = build_rundown(all_clusters(stories, cfg, NOW), cfg, NOW)
    news = FakeNews(rundown)
    news.queue.append(rundown.clusters[0])
    play = Playout(cfg, news, NOW)
    total = b""
    for _ in range(fps * 4):
        play.next_frame()
        total += play.next_audio()
    # Exactly 4 s of 48 kHz stereo s16le, and the sting is in it.
    assert len(total) == 4 * sound.RATE * 4
    assert any(total[: sound.RATE * 4])
    assert not any(total[-4000:])     # the 2.4 s sting is over by the end


def test_ffmpeg_args_have_the_effects_input():
    from pathlib import Path

    args = ffmpeg_args(Config(), Path("/m.txt"), fx_input="pipe:9")
    assert "pipe:9" in args and "s16le" in args
    graph = args[args.index("-filter_complex") + 1]
    assert "sidechaincompress" in graph and "anullsrc" not in " ".join(args)
