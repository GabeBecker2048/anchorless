"""Breaking-news stings, synthesized here (no samples, nothing to license).

Each sting is 48 kHz stereo signed 16-bit PCM. "chiptune" is an 8-bit fanfare
for the Studio look; "news" is a synth-brass "dun dun DUNNN" with a timpani hit
for the Classic look. A sound file of your own (any format ffmpeg reads) can be
used instead.
"""

from __future__ import annotations

import logging
import math
import random
import subprocess
from array import array
from functools import lru_cache

log = logging.getLogger(__name__)

RATE = 48000
STINGS = ("chiptune", "news")


def _hz(note: str) -> float:
    names = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
    name, octave = note[:-1], int(note[-1])
    return 440.0 * 2 ** ((names[name] + 12 * (octave + 1) - 69) / 12)


class _Track:
    """A mono float buffer to add notes into."""

    def __init__(self, seconds: float) -> None:
        self.buf = [0.0] * int(seconds * RATE)

    def add(self, start: float, samples: list[float]) -> None:
        i0 = int(start * RATE)
        buf = self.buf
        for i, v in enumerate(samples, i0):
            if i >= len(buf):
                break
            buf[i] += v


def _env(n: int, attack: float, release: float, sustain: float = 1.0, decay: float = 0.0) -> list[float]:
    """Attack, optional exponential decay towards ``sustain``, linear release at the end."""
    a = max(1, int(attack * RATE))
    r = max(1, int(release * RATE))
    out = []
    for i in range(n):
        if i < a:
            v = i / a
        else:
            t = (i - a) / RATE
            v = sustain + (1 - sustain) * (math.exp(-t / decay) if decay else 1)
        if i > n - r:
            v *= (n - i) / r
        out.append(v)
    return out


def _wavetable(harmonics: list[float], size: int = 2048) -> list[float]:
    table = [sum(a * math.sin(2 * math.pi * (k + 1) * i / size) for k, a in enumerate(harmonics) if a)
             for i in range(size)]
    peak = max(abs(v) for v in table) or 1
    return [v / peak for v in table]


def _osc(table: list[float], hz: float, n: int, vibrato: float = 0.0, vib_rate: float = 6.0,
         vib_delay: float = 0.0, detune: float = 0.0) -> list[float]:
    size = len(table)
    phase = random.random() * size
    out = []
    for i in range(n):
        f = hz * (1 + detune)
        t = i / RATE
        if vibrato and t > vib_delay:
            f *= 1 + vibrato * math.sin(2 * math.pi * vib_rate * t)
        phase = (phase + f * size / RATE) % size
        out.append(table[int(phase)])
    return out


def _square(hz: float, n: int, duty: float = 0.5, vibrato: float = 0.0, vib_delay: float = 0.15) -> list[float]:
    out, phase = [], 0.0
    for i in range(n):
        f = hz
        if vibrato and i / RATE > vib_delay:
            f *= 1 + vibrato * math.sin(2 * math.pi * 6.5 * i / RATE)
        phase = (phase + f / RATE) % 1
        out.append(1.0 if phase < duty else -1.0)
    return out


def _triangle(hz: float, n: int) -> list[float]:
    out, phase = [], 0.0
    for _ in range(n):
        phase = (phase + hz / RATE) % 1
        out.append(4 * abs(phase - 0.5) - 1)
    return out


def _noise(n: int, rng: random.Random, steps: int = 1) -> list[float]:
    """White noise, held for ``steps`` samples (a held value sounds like an NES drum)."""
    out, v = [], 0.0
    for i in range(n):
        if i % steps == 0:
            v = rng.uniform(-1, 1)
        out.append(v)
    return out


def _mul(a: list[float], b: list[float], gain: float = 1.0) -> list[float]:
    return [x * y * gain for x, y in zip(a, b, strict=False)]


def _to_pcm(left: list[float], right: list[float] | None = None, peak: float = 0.89) -> bytes:
    right = right if right is not None else left
    top = max(max(abs(v) for v in left), max(abs(v) for v in right)) or 1
    k = peak * 32767 / top
    pcm = array("h")
    for lv, rv in zip(left, right, strict=True):
        pcm.append(int(lv * k))
        pcm.append(int(rv * k))
    return pcm.tobytes()


def chiptune() -> bytes:
    """DA-DA-DA DAAAA: an 8-bit fanfare. Square-wave chords, triangle bass, noise snare."""
    rng = random.Random(7)
    length = 2.4
    lead, harm, bass, drums = _Track(length), _Track(length), _Track(length), _Track(length)
    stab = 0.1
    for t in (0.0, 0.14, 0.28):                                   # three quick stabs
        n = int(stab * RATE)
        e = _env(n, 0.004, 0.03)
        lead.add(t, _mul(_square(_hz("G5"), n, 0.25), e, 0.30))
        harm.add(t, _mul(_square(_hz("C5"), n, 0.5), e, 0.22))
        harm.add(t, _mul(_square(_hz("E5"), n, 0.5), e, 0.18))
        bass.add(t, _mul(_triangle(_hz("C3"), n), e, 0.5))
        dn = int(0.09 * RATE)
        drums.add(t, _mul(_noise(dn, rng, 3), _env(dn, 0.001, 0.08, 0.0, 0.03), 0.35))
    t = 0.46                                                      # the big held chord
    n = int(1.75 * RATE)
    e = _env(n, 0.006, 0.45, 0.55, 0.35)
    lead.add(t, _mul(_square(_hz("C6"), n, 0.25, vibrato=0.012), e, 0.30))
    harm.add(t, _mul(_square(_hz("G5"), n, 0.5, vibrato=0.010), e, 0.18))
    harm.add(t, _mul(_square(_hz("E5"), n, 0.5, vibrato=0.010), e, 0.16))
    bass.add(t, _mul(_triangle(_hz("C2"), n), _env(n, 0.004, 0.4, 0.7, 0.5), 0.6))
    dn = int(0.45 * RATE)
    drums.add(t, _mul(_noise(dn, rng, 1), _env(dn, 0.001, 0.4, 0.0, 0.12), 0.30))   # crash
    for k, note in enumerate(("C7", "G6", "E6", "C6")):          # a sparkle on top
        sn = int(0.07 * RATE)
        lead.add(t + 0.9 + k * 0.07, _mul(_square(_hz(note), sn, 0.125), _env(sn, 0.002, 0.03), 0.10))
    mix = [a + b + c + d for a, b, c, d in zip(lead.buf, harm.buf, bass.buf, drums.buf, strict=True)]
    # Slight stereo: lead a touch left, harmony a touch right.
    left = [m + 0.15 * a - 0.1 * b for m, a, b in zip(mix, lead.buf, harm.buf, strict=True)]
    right = [m - 0.15 * a + 0.1 * b for m, a, b in zip(mix, lead.buf, harm.buf, strict=True)]
    return _to_pcm(left, right)


def news() -> bytes:
    """Dun, dun, DUNNN: synth brass in D minor, a timpani hit, a rising whoosh."""
    rng = random.Random(11)
    length = 3.0
    brass, low, perc = _Track(length), _Track(length), _Track(length)
    # Brass: a sawtooth-ish wavetable, gently filtered (fewer high harmonics).
    saw = _wavetable([1 / k * (0.92 ** k) for k in range(1, 16)])
    def chord(t: float, notes: list[str], dur: float, gain: float, release: float, vib: float = 0.0) -> None:
        n = int(dur * RATE)
        e = _env(n, 0.035, release, 0.7, 0.25)
        for note in notes:
            for det in (-0.004, 0.004):                            # two detuned voices per note
                brass.add(t, _mul(_osc(saw, _hz(note), n, vibrato=vib, vib_delay=0.4, detune=det), e, gain))
    chord(0.18, ["D4", "F4", "A4"], 0.2, 0.11, 0.06)
    chord(0.48, ["D4", "F4", "A4"], 0.2, 0.11, 0.06)
    chord(0.78, ["D4", "A4", "D5", "F5"], 2.1, 0.12, 0.9, vib=0.004)
    # Low strings under the held chord.
    n = int(2.1 * RATE)
    low.add(0.78, _mul(_osc(saw, _hz("D2"), n, detune=0.002), _env(n, 0.08, 0.9, 0.8, 0.5), 0.22))
    # Timpani: a sine with a falling pitch plus a thud of noise, on each hit.
    for t, g in ((0.18, 0.5), (0.48, 0.5), (0.78, 0.9)):
        tn = int(0.9 * RATE)
        out, ph = [], 0.0
        for i in range(tn):
            f = _hz("D2") * (1 + 0.5 * math.exp(-i / (0.03 * RATE)))
            ph += 2 * math.pi * f / RATE
            out.append(math.sin(ph))
        perc.add(t, _mul(out, _env(tn, 0.002, 0.3, 0.0, 0.28), g))
        nn = int(0.06 * RATE)
        perc.add(t, _mul(_noise(nn, rng, 2), _env(nn, 0.001, 0.05, 0.0, 0.02), g * 0.3))
    # A rising whoosh into the first hit: filtered noise swelling up.
    wn = int(0.2 * RATE)
    noise, acc = _noise(wn, rng), 0.0
    whoosh = []
    for i, v in enumerate(noise):
        acc += (v - acc) * (0.02 + 0.3 * i / wn)                   # the filter opens as it rises
        whoosh.append(acc * (i / wn) ** 2)
    perc.add(0.0, _mul(whoosh, [1.0] * wn, 0.6))
    mix = [a + b + c for a, b, c in zip(brass.buf, low.buf, perc.buf, strict=True)]
    return _to_pcm(mix)


def decode_file(path: str) -> bytes:
    """A sound file of your own, as 48 kHz stereo s16le (ffmpeg decodes it)."""
    try:
        r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-t", "15", "-f", "s16le", "-ac", "2",
                            "-ar", str(RATE), "pipe:1"], capture_output=True, check=False)
    except OSError as err:                     # no ffmpeg on the PATH
        raise ValueError(f"cannot read sound file {path}: {err}") from err
    if r.returncode != 0 or not r.stdout:
        raise ValueError(f"cannot read sound file {path}: {r.stderr.decode(errors='replace').strip()[:200]}")
    return r.stdout


@lru_cache(maxsize=8)
def sting(name: str, theme: str = "studio") -> bytes | None:
    """The PCM for a configured sting: "auto" picks by theme; "none" is silence."""
    if name == "none":
        return None
    if name == "auto":
        name = "chiptune" if theme == "studio" else "news"
    if name == "chiptune":
        return chiptune()
    if name == "news":
        return news()
    try:
        return decode_file(name)
    except ValueError as err:
        log.warning("%s - no breaking-news sound", err)
        return None


def scale(pcm: bytes, volume: float) -> bytes:
    if volume == 1.0:
        return pcm
    a = array("h")
    a.frombytes(pcm)
    for i, v in enumerate(a):
        a[i] = max(-32768, min(32767, int(v * volume)))
    return a.tobytes()
