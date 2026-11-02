from datetime import UTC, datetime, timedelta

import pytest

from anchorless.config import Config
from anchorless.models import Rundown
from anchorless.pipeline import all_clusters, build_rundown
from anchorless.stream.encoder import ffmpeg_args
from anchorless.stream.guide import guide, playlist
from anchorless.stream.playout import Playout
from anchorless.stream.tsbuffer import TS, TsBuffer, is_keyframe

from .conftest import CHANNEL, NOW


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
    cfg.channel.theme = theme
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
    cfg = Config(channel=CHANNEL)
    cfg.channel.theme = theme
    cfg.video.fps = 2
    play = Playout(cfg, FakeNews(Rundown(segments=[], built_at=NOW)), NOW)
    play.next_frame()
    assert play.on_air == "stand by"


def test_guide_and_playlist_with_an_extra_channel():
    from anchorless.config import ExtraChannelConfig

    cfg = Config(channel=CHANNEL, extra_channel=[
        ExtraChannelConfig(theme="classic", name="NEWS CLASSIC", show_on="both", channel_number=97, id="x.classic")])
    # Half-hour blocks on :00 and :30, through the DST change (2026-11-01 in Chicago,
    # a 25-hour day: 50 blocks, then 48 a day).
    text = guide(cfg, datetime(2026, 11, 1, 12, tzinfo=UTC))
    assert 'start="20261101000000 -0500" stop="20261101003000 -0500"' in text
    assert 'start="20261101013000 -0500" stop="20261101010000 -0600"' in text
    assert 'start="20261101010000 -0600" stop="20261101013000 -0600"' in text
    assert text.count("<channel ") == 2 and text.count("<programme ") == 2 * (50 + 48 + 48)
    # One programme per day, midnight to midnight.
    daily = Config(channel={**CHANNEL, "guide_slot_minutes": 1440}, extra_channel=cfg.extra_channel)
    text = guide(daily, datetime(2026, 11, 1, 12, tzinfo=UTC))
    assert 'start="20261101000000 -0500" stop="20261102000000 -0600"' in text
    assert text.count("<programme ") == 6
    m3u = playlist(cfg, "host:9798").splitlines()
    assert 'tvg-chno="2"' in m3u[1] and m3u[2] == "http://host:9798/live.ts"
    assert 'tvg-chno="97"' in m3u[3] and m3u[4] == "http://host:9798/live/x.classic.ts"
    # A web-only channel is left out of the playlist and the guide; a TV-only one is listed.
    two = Config(channel={**CHANNEL, "show_on": "tv"}, extra_channel=[
        ExtraChannelConfig(theme="classic", name="Try It", show_on="web", channel_number=96)])
    assert two.extra_channel[0].id == "anchorless.try-it" and two.extra_channel[0].channel_number is None
    assert "try-it" not in playlist(two, "host:9798") and "try-it" not in guide(two, NOW)
    assert "anchorless.news" in playlist(two, "host:9798")


def test_ffmpeg_args():
    cfg = Config(channel=CHANNEL)
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

    t = StudioTheme(Config(channel=CHANNEL))
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

    args = ffmpeg_args(Config(channel=CHANNEL), Path("/m.txt"), fx_input="pipe:9")
    assert "pipe:9" in args and "s16le" in args
    graph = args[args.index("-filter_complex") + 1]
    assert "sidechaincompress" in graph and "anullsrc" not in " ".join(args)


def test_web_page_status_and_poster(cfg, stories):
    import asyncio

    from aiohttp.test_utils import TestClient, TestServer

    from anchorless.pipeline import all_clusters, build_rundown
    from anchorless.stream.server import make_app

    async def run():
        app = make_app(cfg)
        room = app["station"].newsroom
        room.rundown = build_rundown(all_clusters(stories, cfg, NOW), cfg, NOW)
        async with TestClient(TestServer(app)) as client:
            page = await client.get("/")
            assert page.status == 200 and "mpegts.min.js" in await page.text()
            js = await client.get("/static/mpegts.min.js")
            assert js.status == 200
            st = await (await client.get("/api/status")).json()
            assert st["channels"][0]["stream"] == "/live.ts" and not st["channels"][0]["running"]
            assert st["rundown"] and st["rundown"][0]["stories"][0]["outlets"]
            assert {f["host"] for f in st["feeds"]} == {"a.example", "b.example"}   # hosts, not full URLs
            poster = await client.get(f"/poster/{cfg.channel.id}.png")
            assert poster.status == 200 and (await poster.read())[:4] == b"\x89PNG"
            assert (await client.get("/poster/nope.png")).status == 404

    asyncio.run(run())


def test_hls_segments_start_at_keyframes_and_are_timed_from_pts():
    from anchorless.stream.tsbuffer import TS, TsBuffer

    def pkt(pid, key=False, pts=None):
        p = bytearray(b"\xff" * TS)
        p[0], p[1], p[2] = 0x47, (0x40 if pts is not None else 0) | (pid >> 8), pid & 0xFF
        if key:
            p[3], p[4], p[5] = 0x30, 1, 0x40          # adaptation field with random access
            off = 6
        else:
            p[3] = 0x10
            off = 4
        if pts is not None:
            p[off:off + 9] = b"\x00\x00\x01\xe0\x00\x00\x80\x80\x05"
            p[off + 9:off + 14] = bytes([0x21 | ((pts >> 29) & 0x0E), (pts >> 22) & 0xFF,
                                         ((pts >> 14) & 0xFE) | 1, (pts >> 7) & 0xFF, ((pts << 1) & 0xFE) | 1])
        return bytes(p)

    buf = TsBuffer(lead_seconds=10, gop_seconds=2)
    stream = pkt(0) + pkt(0x1000)                      # PAT, PMT before the first keyframe
    for i in range(4):
        stream += pkt(0x100, key=True, pts=90000 + i * 180000) + pkt(0x100) + pkt(0x101)
    buf.record(stream, now=0.0)
    done = buf.finished()
    assert [s.seq for s in done] == [1, 2, 3]          # the 4th is still growing
    assert all(s.duration == 2.0 for s in done)
    assert len(done[0].data) == 5 * TS                  # PAT + PMT stayed with the first keyframe
    playlist = buf.hls_playlist("/hls/x/{seq}.ts")
    assert "#EXT-X-MEDIA-SEQUENCE:1" in playlist and "/hls/x/3.ts" in playlist and "/hls/x/4.ts" not in playlist
    seg = buf.hls_segment(2)
    assert seg[:2 * TS] == pkt(0) + pkt(0x1000) and buf.hls_segment(4) is None
