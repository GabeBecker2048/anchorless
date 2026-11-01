"""A short memory of the output, so a viewer who joins a running stream starts fast.

A new viewer is sent the stream from the keyframe produced about
``lead_seconds`` ago, all at once. Their player then has as much buffered as
the first viewer's did, and starts just as quickly.

MPEG-TS from ffmpeg: 188-byte packets, PAT on PID 0, PMT on 0x1000, video on
0x100. A video packet with the random-access flag starts a keyframe.
"""

from __future__ import annotations

from collections import deque

TS = 188
PAT_PID = 0
PMT_PID = 0x1000
VIDEO_PID = 0x100


def is_keyframe(p: bytes) -> bool:
    pid = ((p[1] & 0x1F) << 8) | p[2]
    return (pid == VIDEO_PID and bool(p[1] & 0x40)          # payload unit start
            and bool(p[3] & 0x20) and p[4] > 0               # has an adaptation field
            and bool(p[5] & 0x40))                           # random access indicator


class TsBuffer:
    def __init__(self, lead_seconds: float, gop_seconds: float) -> None:
        self.lead = lead_seconds
        self.keep = lead_seconds + gop_seconds + 3
        self.segments: deque[tuple[float, bytearray]] = deque()
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
            if not self.segments or is_keyframe(p):
                self.segments.append((now, bytearray()))
            self.segments[-1][1].extend(p)
        self.rest = bytes(buf[off:])
        cutoff = now - self.keep
        while len(self.segments) > 1 and self.segments[1][0] < cutoff:
            self.segments.popleft()

    @property
    def partial(self) -> int:
        """Bytes of a packet already received but not yet complete."""
        return len(self.rest)

    def head_start(self, now: float) -> bytes:
        """PAT + PMT, then everything from the keyframe produced about ``lead`` seconds ago."""
        target = now - self.lead
        start = 0
        for i, (t, _) in enumerate(self.segments):
            if t <= target:
                start = i
        parts = [p for p in (self.pat, self.pmt) if p]
        parts += [bytes(seg) for _, seg in list(self.segments)[start:]]
        return b"".join(parts)

    def __bool__(self) -> bool:
        return bool(self.segments)
