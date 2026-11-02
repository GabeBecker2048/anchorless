"""The ffmpeg process: raw frames in, H.264 + AAC out (MPEG-TS, or MP4 for previews)."""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import logging
import os
import random
import tempfile
from pathlib import Path

from ..config import Config

log = logging.getLogger(__name__)

F_SETPIPE_SZ = getattr(fcntl, "F_SETPIPE_SZ", 1031)  # Linux

MUSIC_EXTENSIONS = (".mp3",)
# The playlist is written out this many times, reshuffled each pass, and read
# straight through. Not `-stream_loop -1`: the concat demuxer cannot rewind
# (the stream loses its audio track at the end of the first pass).
MUSIC_PASSES = 40


def music_files(music_dir: str | None) -> list[Path]:
    if not music_dir:
        return []
    try:
        return sorted(p for p in Path(music_dir).iterdir() if p.suffix.lower() in MUSIC_EXTENSIONS)
    except OSError as err:
        log.warning("music folder %s unreadable: %s", music_dir, err)
        return []


def write_music_list(files: list[Path], path: Path, passes: int = MUSIC_PASSES) -> None:
    lines = []
    files = list(files)
    for _ in range(passes):
        random.shuffle(files)
        for f in files:
            quoted = str(f.resolve()).replace("'", "'\\''")
            lines.append(f"file '{quoted}'")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def frame_format(cfg: Config) -> str:
    """The raw frame layout the encoder expects: Pillow's packer name."""
    v = cfg.video
    return "BGRX" if v.encoder == "vaapi" and v.vaapi_convert == "gpu" else "RGB"


def ffmpeg_args(cfg: Config, music_list: Path | None, output: str = "pipe:1", fmt: str = "mpegts",
                duration: float | None = None) -> list[str]:
    v, a = cfg.video, cfg.audio
    vaapi = v.encoder == "vaapi"
    gop = max(1, round(v.fps * v.gop_seconds))
    args = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin"]
    if vaapi:
        args += ["-vaapi_device", v.vaapi_device]
    gpu_convert = vaapi and v.vaapi_convert == "gpu"
    args += ["-f", "rawvideo", "-pix_fmt", "bgr0" if gpu_convert else "rgb24", "-s", f"{v.width}x{v.height}", "-framerate", str(v.fps),
             "-thread_queue_size", "256", "-i", "pipe:0"]
    # No -re anywhere: the music is read only as fast as the video timeline needs it.
    if music_list:
        args += ["-f", "concat", "-safe", "0", "-i", str(music_list)]
    args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]

    # Our frames are full-range RGB; TV video is limited-range BT.709.
    if gpu_convert:
        video = "[0:v]hwupload,scale_vaapi=format=nv12:out_color_matrix=bt709:out_range=tv[v]"
    else:
        video = "[0:v]scale=out_color_matrix=bt709:out_range=tv," + ("format=nv12,hwupload" if vaapi
                                                                     else "format=yuv420p") + "[v]"
    if music_list:
        # The silent track keeps audio flowing even if the music runs out or fails.
        audio = f"[1:a]volume={a.volume},aresample=48000[m];[m][2:a]amix=inputs=2:duration=longest:normalize=0[a]"
    else:
        audio = "[1:a]anull[a]"
    args += ["-filter_complex", f"{video};{audio}", "-map", "[v]", "-map", "[a]"]

    if vaapi:
        args += ["-c:v", "h264_vaapi", "-profile:v", "high", "-bf", "0"]
    else:
        # SPS/PPS on every keyframe, so a client joining mid-stream can decode.
        args += ["-c:v", "libx264", "-preset", v.x264_preset, "-tune", "zerolatency", "-profile:v", "high",
                 "-x264-params", "repeat-headers=1", "-keyint_min", str(gop), "-sc_threshold", "0"]
        if v.x264_threads:
            args += ["-threads", str(v.x264_threads)]
    if vaapi and v.vaapi_rc == "cqp":
        rate = ["-rc_mode", "CQP", "-qp", str(v.vaapi_qp)]
    else:
        rate = ["-b:v", v.bitrate, "-maxrate", v.maxrate, "-bufsize", _double(v.maxrate)]
    args += ["-g", str(gop), *rate,
             "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
             "-c:a", "aac", "-b:a", a.bitrate, "-ar", "48000", "-ac", "2"]
    if fmt == "mpegts":
        args += ["-flush_packets", "1", "-muxdelay", "0", "-muxpreload", "0", "-f", "mpegts", output]
    else:
        # The audio never ends on its own (the silent track is endless): cut it.
        args += (["-t", f"{duration:.3f}"] if duration else []) + ["-movflags", "+faststart", "-y", "-f", fmt, output]
    return args


def _double(rate: str) -> str:
    units = {"k": 1_000, "m": 1_000_000}
    s = rate.strip().lower()
    mult = units.get(s[-1], 1)
    num = float(s[:-1]) if s[-1] in units else float(s)
    return str(int(num * mult * 2))


class Encoder:
    """One ffmpeg process for one viewing session."""

    def __init__(self, cfg: Config, output: str = "pipe:1", fmt: str = "mpegts",
                 duration: float | None = None) -> None:
        self.cfg = cfg
        self.duration = duration
        self.output = output
        self.fmt = fmt
        self.proc: asyncio.subprocess.Process | None = None
        self._tmp = tempfile.TemporaryDirectory(prefix="anchorless-")
        self.tracks = 0
        self._stderr_task: asyncio.Task | None = None
        self._in: int | None = None       # our end of ffmpeg's stdin (a plain pipe)

    async def start(self) -> None:
        files = music_files(self.cfg.audio.music_dir)
        self.tracks = len(files)
        music_list = None
        if files:
            music_list = Path(self._tmp.name) / "music.txt"
            write_music_list(files, music_list)
        args = ffmpeg_args(self.cfg, music_list, self.output, self.fmt, self.duration)
        log.debug("ffmpeg: %s", " ".join(args))
        # Frames go through a plain pipe written with blocking writes from the
        # render thread: asyncio's pipe writer re-copies a 1.2 MB frame several
        # times, which cost more CPU than drawing it.
        r, w = os.pipe()
        with contextlib.suppress(OSError):
            fcntl.fcntl(w, F_SETPIPE_SZ, 1 << 20)
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *args, stdin=r,
                stdout=asyncio.subprocess.PIPE if self.output == "pipe:1" else asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception:
            os.close(w)
            raise
        finally:
            os.close(r)
        self._in = w
        self._stderr_task = asyncio.create_task(self._log_stderr())

    async def _log_stderr(self) -> None:
        assert self.proc and self.proc.stderr
        while line := await self.proc.stderr.readline():
            text = line.decode(errors="replace").rstrip()
            # VAAPI ignores the buffer settings in its default rate control: harmless.
            if text and "not supported by this driver" not in text:
                log.warning("ffmpeg: %s", text)

    def write_blocking(self, frame: bytes | memoryview) -> None:
        """Send one frame (call from a worker thread). Raises OSError once ffmpeg is gone."""
        view = memoryview(frame)
        while view:
            fd = self._in       # re-read: stop() may close it from the event loop
            if fd is None:
                raise BrokenPipeError("encoder input closed")
            n = os.write(fd, view)
            view = view[n:]

    async def read(self, n: int = 65536) -> bytes:
        assert self.proc and self.proc.stdout
        return await self.proc.stdout.read(n)

    def close_input(self) -> None:
        fd, self._in = self._in, None
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)

    async def finish(self, timeout: float = 30) -> int | None:
        """Close the input and wait for ffmpeg to write the rest (for files)."""
        if not self.proc:
            return None
        self.close_input()
        try:
            return await asyncio.wait_for(self.proc.wait(), timeout)
        except TimeoutError:
            self.proc.kill()
            return await self.proc.wait()
        finally:
            self._tmp.cleanup()

    async def stop(self) -> None:
        if not self.proc:
            return
        self.close_input()
        if self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), 5)
            except TimeoutError:
                self.proc.kill()
                await self.proc.wait()
        if self._stderr_task:
            self._stderr_task.cancel()
        self._tmp.cleanup()
