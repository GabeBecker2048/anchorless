"""The configuration: one TOML file, validated by pydantic.

Every setting has a default, so an empty file (or none) gives a working channel.
Any value can also be overridden from the environment with
``ANCHORLESS__<SECTION>__<KEY>``, e.g. ``ANCHORLESS__LOCATION__CITY=Springfield``.
That keeps personal details such as the location out of the config file, so it
can be shared or committed.
"""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

Scope = Literal["local", "national", "world"]


class _Model(BaseModel):
    # Unknown keys are errors: a typo should not be silently ignored.
    model_config = ConfigDict(extra="forbid")


class ChannelConfig(_Model):
    name: str = "NEWS"
    number: str = "98"
    id: str = "anchorless.news"
    timezone: str = "America/Chicago"
    guide_title: str = "Anchorless News"
    guide_description: str = "Around-the-clock headlines from national and world news outlets."

    @field_validator("number", mode="before")
    @classmethod
    def _number_as_text(cls, v: Any) -> str:
        return str(v)

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as err:
            raise ValueError(f"unknown timezone {v!r}") from err
        return v


class LocationConfig(_Model):
    """Used for local news (phase 2). Best set from the environment."""

    city: str | None = None
    region: str | None = None
    country: str | None = None


class VideoConfig(_Model):
    width: int = Field(854, ge=320, le=3840)
    height: int = Field(480, ge=240, le=2160)
    fps: int = Field(24, ge=1, le=60)
    encoder: Literal["x264", "vaapi"] = "x264"
    vaapi_device: str = "/dev/dri/renderD128"
    # "vbr" uses bitrate/maxrate. Older Intel drivers (i965) only do "cqp" (constant quality).
    vaapi_rc: Literal["vbr", "cqp"] = "vbr"
    vaapi_qp: int = Field(24, ge=1, le=51)
    # Where RGB becomes the encoder's YUV: "cpu" (works everywhere) or "gpu"
    # (scale_vaapi; saves most of ffmpeg's CPU, needs a driver with video processing).
    vaapi_convert: Literal["cpu", "gpu"] = "cpu"
    bitrate: str = "1500k"
    maxrate: str = "2000k"
    gop_seconds: float = Field(2.0, gt=0, le=10)
    x264_preset: str = "veryfast"
    # 0 = ffmpeg's choice (fastest start). Fewer threads use less CPU while watching.
    x264_threads: int = Field(0, ge=0, le=64)

    @field_validator("width", "height")
    @classmethod
    def _even(cls, v: int) -> int:
        if v % 2:
            raise ValueError("must be even (H.264 4:2:0 needs even dimensions)")
        return v


class AudioConfig(_Model):
    music_dir: str | None = "/music"
    volume: float = Field(0.5, ge=0, le=2)
    bitrate: str = "128k"


class StreamConfig(_Model):
    host: str = "0.0.0.0"
    port: int = Field(9798, ge=1, le=65535)
    # Rendered ahead at once for a new viewer. Samsung TV players buffer about
    # 10 s before they show anything, so less than that means a longer black screen.
    lead_seconds: float = Field(10.0, ge=0, le=30)
    # Stop encoding this long after the last viewer leaves.
    idle_seconds: float = Field(60.0, ge=0)


class SegmentConfig(_Model):
    name: str
    stories: int = Field(3, ge=1, le=20)
    # Which stories may appear: none set = any story (e.g. TOP STORIES).
    scope: Scope | None = None
    category: str | None = None


def _default_segments() -> list[SegmentConfig]:
    return [
        SegmentConfig(name="TOP STORIES", stories=4),
        SegmentConfig(name="NATIONAL", stories=3, scope="national"),
        SegmentConfig(name="WORLD", stories=3, scope="world"),
        SegmentConfig(name="BUSINESS", stories=2, category="business"),
    ]


class RundownConfig(_Model):
    refresh_minutes: float = Field(10, ge=1)
    page_seconds: float = Field(12, ge=3)
    intro_seconds: float = Field(5, ge=0)
    transition_seconds: float = Field(0.4, ge=0, le=2)
    max_story_age_hours: float = Field(12, gt=0)
    # Two headlines with at least this much word overlap are the same story.
    same_story_similarity: float = Field(0.5, gt=0, le=1)
    # ...or whose headlines and summaries score at least this (TF-IDF cosine).
    same_story_text_similarity: float = Field(0.32, gt=0, le=1)
    segment: list[SegmentConfig] = Field(default_factory=_default_segments)


class BreakingConfig(_Model):
    enabled: bool = True
    min_sources: int = Field(4, ge=2)
    window_minutes: float = Field(30, gt=0)
    cooldown_minutes: float = Field(20, ge=0)
    crawl_tag_minutes: float = Field(60, ge=0)
    title_prefixes: list[str] = Field(default_factory=lambda: ["BREAKING:", "BREAKING NEWS:"])


class SourceConfig(_Model):
    type: Literal["rss"] = "rss"
    # The outlet's name, shown on screen. Feeds with the same name count as one
    # outlet when counting how many outlets carry a story.
    name: str
    url: str
    scope: Scope = "national"
    category: str = "general"
    weight: float = Field(1.0, ge=0)
    enabled: bool = True
    # Skip items whose headline or link matches any of these regular expressions.
    exclude: list[str] = Field(default_factory=list)

    @field_validator("exclude")
    @classmethod
    def _valid_patterns(cls, v: list[str]) -> list[str]:
        for pattern in v:
            try:
                re.compile(pattern)
            except re.error as err:
                raise ValueError(f"bad pattern {pattern!r}: {err}") from err
        return v


def _rss(name: str, url: str, scope: Scope = "national", category: str = "general", **kw: Any) -> SourceConfig:
    return SourceConfig(name=name, url=url, scope=scope, category=category, **kw)


def default_sources() -> list[SourceConfig]:
    """Major outlets' public RSS feeds, checked working on 2026-11-01."""
    nyt = "https://rss.nytimes.com/services/xml/rss/nyt/"
    cnbc = "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id="
    return [
        _rss("NPR", "https://feeds.npr.org/1001/rss.xml"),
        _rss("NPR", "https://feeds.npr.org/1003/rss.xml"),
        _rss("NPR", "https://feeds.npr.org/1004/rss.xml", "world"),
        _rss("NPR", "https://feeds.npr.org/1006/rss.xml", category="business"),
        _rss("The New York Times", nyt + "HomePage.xml"),
        _rss("The New York Times", nyt + "US.xml"),
        _rss("The New York Times", nyt + "World.xml", "world"),
        _rss("The New York Times", nyt + "Business.xml", category="business"),
        _rss("CBS News", "https://www.cbsnews.com/latest/rss/us"),
        _rss("CBS News", "https://www.cbsnews.com/latest/rss/world", "world"),
        _rss("CBS News", "https://www.cbsnews.com/latest/rss/moneywatch", category="business"),
        _rss("ABC News", "https://feeds.abcnews.com/abcnews/topstories"),
        _rss("NBC News", "https://feeds.nbcnews.com/nbcnews/public/news"),
        _rss("Fox News", "https://moxie.foxnews.com/google-publisher/latest.xml"),
        _rss("The Guardian", "https://www.theguardian.com/us-news/rss"),
        _rss("The Guardian", "https://www.theguardian.com/world/rss", "world"),
        _rss("BBC News", "https://feeds.bbci.co.uk/news/world/rss.xml", "world"),
        _rss("BBC News", "https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml"),
        _rss("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml", "world"),
        # /select/ is CNBC's shopping and credit-card advice, not news.
        _rss("CNBC", cnbc + "10001147", category="business", exclude=["/select/"]),
        _rss("CNBC", cnbc + "100003114", category="business", exclude=["/select/"]),
    ]


class ThemeConfig(_Model):
    name: Literal["studio", "classic"] = "studio"
    crawl_label: str = "HEADLINES"
    # Pixels per second at 480 lines; scaled with the output height.
    crawl_speed: float = Field(96, gt=0)


class ExtraChannelConfig(_Model):
    """Another channel from the same news, e.g. the same rundown in a different theme."""

    name: str
    number: str
    id: str
    theme: Literal["studio", "classic"] = "classic"

    @field_validator("number", mode="before")
    @classmethod
    def _number_as_text(cls, v: Any) -> str:
        return str(v)


class DataConfig(_Model):
    dir: str = "data"


class Config(_Model):
    channel: ChannelConfig = Field(default_factory=ChannelConfig)
    location: LocationConfig = Field(default_factory=LocationConfig)
    video: VideoConfig = Field(default_factory=VideoConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    stream: StreamConfig = Field(default_factory=StreamConfig)
    rundown: RundownConfig = Field(default_factory=RundownConfig)
    breaking: BreakingConfig = Field(default_factory=BreakingConfig)
    source: list[SourceConfig] = Field(default_factory=default_sources)
    theme: ThemeConfig = Field(default_factory=ThemeConfig)
    extra_channel: list[ExtraChannelConfig] = Field(default_factory=list)
    data: DataConfig = Field(default_factory=DataConfig)

    @model_validator(mode="after")
    def _has_sources(self) -> Config:
        if not any(s.enabled for s in self.source):
            raise ValueError("no enabled [[source]] entries")
        ids = [self.channel.id] + [c.id for c in self.extra_channel]
        if len(set(ids)) != len(ids):
            raise ValueError("channel ids must be unique")
        return self

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.channel.timezone)


class ConfigError(Exception):
    pass


ENV_PREFIX = "ANCHORLESS__"


def _apply_env(raw: dict[str, Any], environ: dict[str, str]) -> dict[str, Any]:
    for key, value in environ.items():
        if not key.startswith(ENV_PREFIX):
            continue
        parts = key[len(ENV_PREFIX):].lower().split("__")
        if len(parts) != 2 or not all(parts):
            raise ConfigError(f"{key}: expected {ENV_PREFIX}<SECTION>__<KEY>")
        section, field = parts
        target = raw.setdefault(section, {})
        if not isinstance(target, dict):
            raise ConfigError(f"{key}: [{section}] is not a table")
        target[field] = value
    return raw


def load_config(path: str | Path | None = None, environ: dict[str, str] | None = None) -> Config:
    """Load the config from ``path`` (or $ANCHORLESS_CONFIG, or ./config.toml if present)."""
    environ = dict(os.environ if environ is None else environ)
    if path is None:
        path = environ.get("ANCHORLESS_CONFIG")
        if path is None and Path("config.toml").exists():
            path = "config.toml"
    raw: dict[str, Any] = {}
    if path is not None:
        try:
            raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError as err:
            raise ConfigError(f"config file not found: {path}") from err
        except tomllib.TOMLDecodeError as err:
            raise ConfigError(f"{path}: {err}") from err
    raw = _apply_env(raw, environ)
    try:
        return Config.model_validate(raw)
    except ValidationError as err:
        lines = [f"{path or 'config'}: invalid settings"]
        for e in err.errors():
            where = ".".join(str(p) for p in e["loc"]) or "(top level)"
            lines.append(f"  {where}: {e['msg']}")
        raise ConfigError("\n".join(lines)) from err
