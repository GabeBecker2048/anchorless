"""The configuration: one TOML file, validated by pydantic.

Almost every setting has a default. A [channel] section with a theme, show_on and
(for a TV channel) a channel_number is all a working file needs.
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


ShowOn = Literal["both", "tv", "web"]
_NUMBER = re.compile(r"^\d+(\.\d+)?$")


class _ChannelSettings(_Model):
    """What [channel] and every [[extra_channel]] have in common."""

    theme: Literal["studio", "classic", "classic-dark"]
    # "both": a TV channel (in /playlist.m3u and /guide.xml) and on the web page;
    # "tv": TV only; "web": web page only. This is where a channel is listed - any
    # channel's stream URL still plays for whoever opens it.
    show_on: ShowOn
    # Required for "both" and "tv" (e.g. 2, 101 or 2.1), ignored for "web".
    channel_number: str | None = None
    # Stable id for TV guides (tvg-id) and the stream URL. Defaults from the name.
    id: str | None = None

    @field_validator("channel_number", mode="before")
    @classmethod
    def _number_as_text(cls, v: Any) -> str | None:
        if v is None:
            return None
        text = str(v).strip()
        if not _NUMBER.match(text):
            raise ValueError(f"channel_number must be a number like 2, 101 or 2.1, not {v!r}")
        return text

    @model_validator(mode="after")
    def _number_when_on_tv(self):
        if self.show_on == "web":
            self.channel_number = None              # ignored for web-only channels
        elif self.channel_number is None:
            raise ValueError(f'channel_number is required when show_on = "{self.show_on}"')
        return self

    @property
    def on_tv(self) -> bool:
        return self.show_on in ("both", "tv")

    @property
    def on_web(self) -> bool:
        return self.show_on in ("both", "web")


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "channel"


class ChannelConfig(_ChannelSettings):
    name: str = "NEWS"
    id: str | None = "anchorless.news"
    timezone: str = "America/Chicago"
    guide_title: str = "Anchorless News"
    guide_description: str = "Around-the-clock headlines from national and world news outlets."
    # The guide lists the newscast in blocks this long, starting on the hour
    # (30 = :00 and :30). 1440 = one programme per day.
    guide_slot_minutes: int = Field(30, ge=5, le=1440)

    @field_validator("guide_slot_minutes")
    @classmethod
    def _divides_the_day(cls, v: int) -> int:
        if 1440 % v:
            raise ValueError("guide_slot_minutes must divide a day evenly (15, 30, 60, ...)")
        return v

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as err:
            raise ValueError(f"unknown timezone {v!r}") from err
        return v


class LocationConfig(_Model):
    """Local news. Best set from the environment, so the location stays out of this file."""

    # Shown as the local segment's title ("{city}" in a segment name).
    city: str | None = None
    region: str | None = None
    country: str | None = None
    # A TOML file of [[source]] entries for local outlets (see local.example.toml).
    # Every source in it is local. Kept apart so the config file names no place.
    sources_file: str | None = None


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
    # Stories only from these scopes are left out (TOP STORIES skips local-only stories).
    exclude_scope: list[Scope] = Field(default_factory=list)


def _default_segments() -> list[SegmentConfig]:
    return [
        SegmentConfig(name="TOP STORIES", stories=4, exclude_scope=["local"]),
        SegmentConfig(name="{city}", stories=3, scope="local"),
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
    # Local-only stories need more outlets (local newsrooms all cover the same
    # things). A "BREAKING:" headline still counts. "log" only logs what would
    # have broken in; "off" never breaks in for local-only stories.
    local_min_sources: int = Field(5, ge=2)
    local_alerts: Literal["on", "log", "off"] = "on"
    # "auto" (chiptune for the Studio look, "news" for Classic), "chiptune", "news",
    # "none", or the path of a sound file of your own.
    sound: str = "auto"
    sound_volume: float = Field(0.8, ge=0, le=2)


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
    # false: ask for the feed uncompressed. Some servers never answer
    # an HTTP/1.1 request that accepts gzip.
    compressed: bool = True
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


class CrawlConfig(_Model):
    """The headline crawl along the bottom, on every channel."""

    label: str = "HEADLINES"
    # Pixels per second at 480 lines; scaled with the output height.
    speed: float = Field(96, gt=0)


class ExtraChannelConfig(_ChannelSettings):
    """Another channel from the same news: the same settings as [channel], but
    the name is required (and the guide, timezone etc. are shared with [channel])."""

    name: str

    @model_validator(mode="after")
    def _default_id(self):
        if not self.id:
            self.id = "anchorless." + _slug(self.name)
        return self


class DataConfig(_Model):
    dir: str = "data"


class FeedsConfig(_Model):
    """Which feeds run: the built-in list, plus [[source]] entries, plus local feeds."""

    # false: leave out the built-in national/world feeds (then [[source]] lists all of them).
    builtin: bool = True
    # Feed URLs to skip (any feed: built-in, [[source]] or local).
    disabled: list[str] = Field(default_factory=list)


def _private_ranges() -> list[str]:
    return ["127.0.0.0/8", "::1/128", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
            "100.64.0.0/10", "fc00::/7", "fe80::/10"]


class AdminConfig(_Model):
    """The settings page (/settings). Off unless a password is set - best from the
    environment: ANCHORLESS__ADMIN__PASSWORD."""

    password: str | None = None
    # Who may open the settings page at all (CIDR ranges). Default: this machine and private networks.
    allow_from: list[str] = Field(default_factory=_private_ranges)
    # Reverse proxies whose X-Forwarded-For is believed (e.g. Caddy). Empty: none.
    trusted_proxies: list[str] = Field(default_factory=list)
    session_days: float = Field(30, gt=0, le=365)

    @field_validator("allow_from", "trusted_proxies")
    @classmethod
    def _networks(cls, v: list[str]) -> list[str]:
        import ipaddress
        for net in v:
            try:
                ipaddress.ip_network(net, strict=False)
            except ValueError as err:
                raise ValueError(f"not an address or CIDR range: {net!r}") from err
        return v


class Config(_Model):
    channel: ChannelConfig
    location: LocationConfig = Field(default_factory=LocationConfig)
    video: VideoConfig = Field(default_factory=VideoConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    stream: StreamConfig = Field(default_factory=StreamConfig)
    rundown: RundownConfig = Field(default_factory=RundownConfig)
    breaking: BreakingConfig = Field(default_factory=BreakingConfig)
    source: list[SourceConfig] = Field(default_factory=default_sources)
    crawl: CrawlConfig = Field(default_factory=CrawlConfig)
    extra_channel: list[ExtraChannelConfig] = Field(default_factory=list)
    feeds: FeedsConfig = Field(default_factory=FeedsConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    admin: AdminConfig = Field(default_factory=AdminConfig)

    @model_validator(mode="after")
    def _has_sources(self) -> Config:
        if not any(s.enabled for s in self.source):
            raise ValueError("no enabled feeds (all are off, or [feeds] builtin = false with no [[source]])")
        channels = [self.channel, *self.extra_channel]
        ids = [c.id for c in channels]
        if len(set(ids)) != len(ids):
            raise ValueError("channel ids must be unique (two channels have the same name? set id)")
        numbers = [c.channel_number for c in channels if c.on_tv]
        if len(set(numbers)) != len(numbers):
            raise ValueError("two TV channels have the same channel_number")
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


def _renamed_keys(raw: dict[str, Any]) -> None:
    """Clear errors for settings that moved, instead of "extra inputs are not permitted"."""
    moved = []
    old_theme = raw.get("theme")
    if isinstance(old_theme, dict):
        if "name" in old_theme:
            moved.append('[theme] name is now [channel] theme')
        if "crawl_label" in old_theme:
            moved.append("[theme] crawl_label is now [crawl] label")
        if "crawl_speed" in old_theme:
            moved.append("[theme] crawl_speed is now [crawl] speed")
        if not old_theme.keys() - {"name", "crawl_label", "crawl_speed"} and not moved:
            moved.append("[theme] is now [crawl]")
    for where, ch in [("[channel]", raw.get("channel") or {})] + [
            ("[[extra_channel]]", x) for x in raw.get("extra_channel") or [] if isinstance(x, dict)]:
        if "number" in ch:
            moved.append(f"{where} number is now channel_number")
        if "in_guide" in ch:
            moved.append(f'{where} in_guide is now show_on ("both", "tv" or "web")')
    if moved:
        raise ConfigError("settings that moved: " + "; ".join(moved))


def _local_sources(text: str, where: str) -> list[dict[str, Any]]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as err:
        raise ConfigError(f"{where}: {err}") from err
    sources = data.get("source") or []
    if not isinstance(sources, list):
        raise ConfigError(f"{where}: expected [[source]] entries")
    return [{**src, "scope": "local"} for src in sources]


def env_keys(environ: dict[str, str]) -> set[tuple[str, str]]:
    """The (section, key) pairs the environment sets: they override the file."""
    out = set()
    for key in environ:
        if key.startswith(ENV_PREFIX):
            parts = key[len(ENV_PREFIX):].lower().split("__")
            if len(parts) == 2:
                out.add((parts[0], parts[1]))
    return out


def resolve_local_path(config_path: str | Path | None, sources_file: str) -> Path:
    return (Path(config_path).parent if config_path else Path()) / sources_file


def parse_config(text: str, environ: dict[str, str], *, path: str | Path | None = None,
                 local_text: str | None = None) -> Config:
    """Validate config text (and the local feeds file's text, if it names one) without
    touching disk - the settings page checks a change this way before writing it.
    ``local_text`` None means: read the local feeds file from disk."""
    try:
        raw: dict[str, Any] = tomllib.loads(text)
    except tomllib.TOMLDecodeError as err:
        raise ConfigError(f"{path or 'config'}: {err}") from err
    raw = _apply_env(raw, environ)
    _renamed_keys(raw)
    feeds = raw.get("feeds") or {}
    if not isinstance(feeds, dict):
        raise ConfigError("[feeds] must be a table")
    # The feeds: built-in ones, plus [[source]] entries, plus the local feeds file.
    sources = [s.model_dump() for s in default_sources()] if feeds.get("builtin", True) else []
    sources += list(raw.get("source") or [])
    sources_file = (raw.get("location") or {}).get("sources_file")
    if sources_file:
        local_path = resolve_local_path(path, sources_file)
        if local_text is None:
            try:
                local_text = local_path.read_text(encoding="utf-8")
            except FileNotFoundError as err:
                raise ConfigError(f"local sources file not found: {local_path}") from err
        sources += _local_sources(local_text, str(local_path))
    disabled = set(feeds.get("disabled") or [])
    raw["source"] = [{**s, "enabled": False} if s.get("url") in disabled else s for s in sources]
    try:
        return Config.model_validate(raw)
    except ValidationError as err:
        lines = [f"{path or 'config'}: invalid settings"]
        for e in err.errors():
            where = ".".join(str(p) for p in e["loc"]) or "(top level)"
            lines.append(f"  {where}: {e['msg']}")
        raise ConfigError("\n".join(lines)) from err


def config_path(environ: dict[str, str] | None = None) -> Path | None:
    """$ANCHORLESS_CONFIG, or ./config.toml if present."""
    environ = os.environ if environ is None else environ
    path = environ.get("ANCHORLESS_CONFIG")
    if path is None and Path("config.toml").exists():
        path = "config.toml"
    return Path(path) if path else None


def load_config(path: str | Path | None = None, environ: dict[str, str] | None = None) -> Config:
    """Load the config from ``path`` (or $ANCHORLESS_CONFIG, or ./config.toml if present)."""
    environ = dict(os.environ if environ is None else environ)
    if path is None:
        path = config_path(environ)
    text = ""
    if path is not None:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except FileNotFoundError as err:
            raise ConfigError(f"config file not found: {path}") from err
    return parse_config(text, environ, path=path)
