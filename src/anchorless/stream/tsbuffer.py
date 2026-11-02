"""A short memory of the output, so a viewer who joins a running stream starts fast.

A new viewer is sent the stream from the keyframe produced about
``lead_seconds`` ago, all at once. Their player then has as much buffered as
the first viewer's did, and starts just as quickly.

The same keyframe-to-keyframe pieces are the HLS segments (for iPhones, which
cannot play a raw MPEG-TS stream): numbered, timed from their PTS, and served
from memory with PAT + PMT in front.

MPEG-TS from ffmpeg: 188-byte packets, PAT on PID 0, PMT on 0x1000, video on
0x100. A video packet with the random-access flag starts a keyframe.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

TS = 188
PAT_PID = 0
PMT_PID = 0x1000
VIDEO_PID = 0x100


def pes_pts(p: bytes) -> int | None:
    """The PTS (90 kHz) of the PES that starts in this packet, if it has one."""
    off = 4 + (1 + p[4] if p[3] & 0x20 else 0)
    if off + 14 > TS or p[off:off + 3] != b"\x00\x00\x01" or not p[off + 7] & 0x80:
        return None
    b = p[off + 9:off + 14]
    return ((b[0] >> 1) & 7) << 30 | b[1] << 22 | (b[2] >> 1) << 15 | b[3] << 7 | b[4] >> 1


@dataclass
class Segment:
    arrived: float                 # monotonic time its first packet arrived
    seq: int                       # HLS media sequence number
    pts: int | None                # of its first (key)frame
    data: bytearray = field(default_factory=bytearray)
    duration: float | None = None  # set when the next segment starts (None: still growing)
    keyed: bool = False            # starts with (or has reached) a keyframe


# HLS keeps at least this many finished segments (~24 s at 2 s each).
HLS_KEEP = 12


def is_keyframe(p: bytes) -> bool:
    pid = ((p[1] & 0x1F) << 8) | p[2]
    return (pid == VIDEO_PID and bool(p[1] & 0x40)          # payload unit start
            and bool(p[3] & 0x20) and p[4] > 0               # has an adaptation field
            and bool(p[5] & 0x40))                           # random access indicator


class TsBuffer:
    def __init__(self, lead_seconds: float, gop_seconds: float) -> None:
        self.lead = lead_seconds
        self.keep = lead_seconds + gop_seconds + 3
        self.gop = gop_seconds
        self.segments: deque[Segment] = deque()
        self._seq = 0
        self.pat: bytes | None = None
        self.pmt: bytes | None = None
        self.rest = b""

    def record(self, chunk: bytes, now: float) -> None:
        buf = self.rest + chunk if self.rest else chunk
        off = 0
        n = len(buf)
        while off + TS <= n:
            if buf[off] != 0x47:          # lost sync: find the next packet start
                off += 1
                continue
            p = bytes(buf[off:off + TS])
            off += TS
            pid = ((p[1] & 0x1F) << 8) | p[2]
            if pid == PAT_PID:
                self.pat = p
            elif pid == PMT_PID:
                self.pmt = p
            key = is_keyframe(p)
            if not self.segments:
                self._start_segment(now, pes_pts(p) if key else None, key)
            elif key:
                last = self.segments[-1]
                if last.keyed:
                    self._start_segment(now, pes_pts(p), True)
                else:
                    # What came before the first keyframe (the PAT/PMT) joins it: a
                    # segment with no picture would be an empty HLS segment.
                    last.keyed, last.pts = True, pes_pts(p)
            self.segments[-1].data.extend(p)
        self.rest = bytes(buf[off:])
        cutoff = now - self.keep
        while len(self.segments) > HLS_KEEP + 1 and self.segments[1].arrived < cutoff:
            self.segments.popleft()

    def _start_segment(self, now: float, pts: int | None, keyed: bool) -> None:
        if self.segments:
            last = self.segments[-1]
            if last.pts is not None and pts is not None:
                last.duration = ((pts - last.pts) % (1 << 33)) / 90000
            else:
                last.duration = self.gop
        self._seq += 1
        self.segments.append(Segment(now, self._seq, pts, keyed=keyed))

    @property
    def partial(self) -> int:
        """Bytes of a packet already received but not yet complete."""
        return len(self.rest)

    def head_start(self, now: float) -> bytes:
        """PAT + PMT, then everything from the keyframe produced about ``lead`` seconds ago."""
        target = now - self.lead
        start = 0
        for i, seg in enumerate(self.segments):
            if seg.arrived <= target:
                start = i
        parts = [p for p in (self.pat, self.pmt) if p]
        parts += [bytes(seg.data) for seg in list(self.segments)[start:]]
        return b"".join(parts)

    # --- HLS ---

    def finished(self) -> list[Segment]:
        """Segments that are complete (the last one is still growing)."""
        return [s for s in self.segments if s.duration is not None]

    def hls_playlist(self, uri: str) -> str:
        """A live media playlist of the finished segments; ``uri`` has a {seq} slot."""
        segs = self.finished()
        target = max([s.duration for s in segs] + [self.gop])
        lines = ["#EXTM3U", "#EXT-X-VERSION:3", f"#EXT-X-TARGETDURATION:{int(target + 0.999)}",
                 f"#EXT-X-MEDIA-SEQUENCE:{segs[0].seq if segs else self._seq}"]
        for s in segs:
            lines += [f"#EXTINF:{s.duration:.3f},", uri.format(seq=s.seq)]
        return "\n".join(lines) + "\n"

    def hls_segment(self, seq: int) -> bytes | None:
        for s in self.segments:
            if s.seq == seq and s.duration is not None:
                return b"".join(p for p in (self.pat, self.pmt) if p) + bytes(s.data)
        return None

    def __bool__(self) -> bool:
        return bool(self.segments)
