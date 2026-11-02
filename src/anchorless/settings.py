"""The settings page's editor: the config file stays the one source of truth.

The browser never holds settings of its own. It reads the current values, and a
save sends only what changed, each change with the value the browser loaded.
Here, under one lock (one writer), the files are read fresh, every change is
checked against what is in the file *now* (a change someone else made since the
page was loaded is a conflict, not an overwrite), the edits are made in place
with tomlkit (comments, order and formatting kept), the result is validated
exactly as a start-up would load it, and only then written - to a temporary
file that replaces the real one in a single rename.

Local feeds are written to the local feeds file ([location] sources_file),
never to config.toml, so their URLs stay out of a config that may be shared.
Settings set from the environment override the file and cannot be changed here.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.items import AoT, Table

from .config import (
    Config,
    ConfigError,
    _slug,
    default_sources,
    env_keys,
    parse_config,
    resolve_local_path,
)
from .render.theme import resolve_look

log = logging.getLogger(__name__)

SOUNDS = ["auto", "chiptune", "news", "none"]

# The settings the page can change, by section: (key, label, help, applies).
# applies: "live" (next fetch / next page) or "restart" (the channel's stream restarts).
SECTIONS: list[tuple[str, str, list[tuple[str, str, str, str]]]] = [
    ("rundown", "Rundown", [
        ("rundown.page_seconds", "Seconds per story", "How long each story stays on screen.", "live"),
        ("rundown.intro_seconds", "Segment intro seconds", "The \"coming up\" page before each segment. 0 = none.", "live"),
        ("rundown.transition_seconds", "Crossfade seconds", "Between pages. 0 = cut.", "live"),
        ("rundown.refresh_minutes", "Fetch news every (minutes)", "How often all feeds are checked.", "live"),
        ("rundown.max_story_age_hours", "Oldest story (hours)", "Stories older than this are dropped.", "live"),
    ]),
    ("breaking", "Breaking news", [
        ("breaking.enabled", "Breaking-news alerts", "Interrupt the rundown for big stories.", "live"),
        ("breaking.min_sources", "Outlets needed", "A story carried by this many outlets within the window breaks in.", "live"),
        ("breaking.window_minutes", "Within (minutes)", "...of the story first appearing.", "live"),
        ("breaking.local_min_sources", "Local outlets needed", "For stories only local outlets carry.", "live"),
        ("breaking.local_alerts", "Local alerts", "\"log\" only logs what would have broken in.", "live"),
        ("breaking.cooldown_minutes", "Minimum gap (minutes)", "At most one alert per this long.", "live"),
        ("breaking.crawl_tag_minutes", "Red crawl tag (minutes)", "How long a breaking story keeps its tag in the crawl.", "live"),
        ("breaking.title_prefixes", "Headline prefixes", "A headline starting with one of these breaks in on its own. One per line.", "live"),
        ("breaking.sound", "Alert sound", "\"auto\": chiptune for Studio, news brass for Classic.", "restart"),
        ("breaking.sound_volume", "Alert sound volume", "1 = as made.", "restart"),
    ]),
    ("look", "Crawl and music", [
        ("crawl.label", "Crawl label", "The box at the left of the crawl.", "restart"),
        ("crawl.speed", "Crawl speed", "Pixels per second at 480 lines.", "restart"),
        ("audio.volume", "Music volume", "1 = as recorded.", "restart"),
    ]),
    ("guide", "TV guide", [
        ("channel.guide_title", "Programme title", "What the TV guide calls the newscast.", "live"),
        ("channel.guide_description", "Programme description", "", "live"),
        ("channel.guide_slot_minutes", "Guide block (minutes)", "Blocks start on the hour. 1440 = one per day.", "live"),
        ("channel.timezone", "Time zone", "For the on-screen clock and the guide (e.g. America/Chicago).", "live"),
    ]),
    ("viewers", "Viewers", [
        ("stream.max_sessions", "Channels on at once", "Each channel being watched costs ~30% of a CPU core; "
         "viewers of a channel that is already on don't count. -1 = no limit, 0 = nobody can watch.", "live"),
        ("stream.max_viewers", "Viewers at once", "All channels together: TV, web page and iPhones. "
         "-1 = no limit, 0 = nobody can watch.", "live"),
        ("stream.max_viewers_per_client", "Viewers per address", "So one client can't take every slot. "
         "A household behind one router, or a TV server like Jellyfin, is one address. -1 = no limit.", "live"),
    ]),
    ("https", "https", [
        ("web.require_https", "Viewer page needs https", "Suggested: on, if you have an https address "
         "(a reverse proxy). TV tuners are not affected: they always use plain http.", "live"),
        ("web.public_status", "Public status detail", "\"full\": the viewer page and /health list each feed "
         "by name and site. \"summary\": counts only. Full URLs and error details are only ever shown here.", "live"),
        ("admin.require_https", "Settings page needs https", "Suggested: on (the default) - plain http "
         "would send your password unencrypted.", "file"),
    ]),
    ("feeds", "Feeds", [
        ("feeds.builtin", "Built-in feeds", "The national and world outlets that come with Anchorless.", "live"),
    ]),
]
# Shown on the page but changed only in the file: the settings page can't switch off its own protection.
SCALAR_KEYS = {key: applies for _, _, fields in SECTIONS for key, _, _, applies in fields if applies != "file"}
FILE_LOCK_NOTE = "CHANGE IT IN THE FILE - THE SETTINGS PAGE CAN'T TURN OFF ITS OWN PROTECTION"
CHANNEL_FIELDS = ["theme", "name", "show_on", "channel_number"]
# Shown on the page, changed only in the file (paths, the encoder, the server, the login).
FILE_ONLY = {
    "video": None, "stream": ["host", "port", "lead_seconds", "idle_seconds"], "data": None,
    "audio": ["music_dir", "bitrate"],
    "location": ["sources_file", "city"],
    "admin": ["allow_from", "trusted_proxies", "session_days"],
    "feeds": ["allow_private"],
}


class SettingsError(Exception):
    status = 400


class Conflict(SettingsError):
    """Someone (or a hand edit) changed these since the page loaded them."""

    status = 409

    def __init__(self, keys: list[str]) -> None:
        super().__init__("changed since you opened the page: " + ", ".join(keys))
        self.keys = keys


class Invalid(SettingsError):
    status = 422


@dataclass
class Files:
    config_path: Path
    config_text: str
    local_path: Path | None
    local_text: str | None

    @property
    def version(self) -> str:
        h = hashlib.sha256(self.config_text.encode())
        h.update(b"\0" + (self.local_text or "").encode())
        return h.hexdigest()[:16]


def _get(cfg: Config, key: str) -> Any:
    section, field = key.split(".")
    return getattr(getattr(cfg, section), field)


def _schema(cfg_cls: type[Config], key: str) -> dict:
    """Type, choices and limits of a setting, from the pydantic models."""
    section, field = key.split(".")
    model = Config.model_fields[section].annotation
    prop = dict(model.model_json_schema()["properties"][field])
    if "anyOf" in prop:          # Optional[...]: take the non-null branch
        prop = {**prop, **next(p for p in prop["anyOf"] if p.get("type") != "null")}
    out = {"type": prop.get("type", "string")}
    if "enum" in prop:
        out["enum"] = prop["enum"]
    if prop.get("type") == "array":
        out["type"] = "list"
    for k in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
        if k in prop:
            out[k] = prop[k]
    if key == "breaking.sound":
        out["enum"] = SOUNDS
    if key == "channel.guide_slot_minutes":
        out["enum"] = [15, 30, 60, 120, 1440]
    return out


def _channel_id(entry: Any) -> str:
    return entry.get("id") or "anchorless." + _slug(str(entry.get("name", "")))


def _blank_line(container: Any) -> None:
    """A blank line before a new section, so appended sections read like hand-written ones."""
    if len(container) and not tomlkit.dumps(container).endswith("\n\n"):
        container.add(tomlkit.nl())


def _append(aot: AoT, table: Table) -> None:
    """Add an entry to an array of tables."""
    aot.append(table)       # spacing: see _tidy_headers


def _aot(container: Any, key: str, create: bool = False) -> AoT | None:
    if key in container:
        return container[key]
    if create:
        _blank_line(container)
        container.append(key, tomlkit.aot())
        return container[key]
    return None


def _table(container: Any, key: str) -> Table:
    if key not in container:
        _blank_line(container)
        container.append(key, tomlkit.table())
    return container[key]


def _set(table: Any, key: str, value: Any) -> None:
    """Set a value, keeping the old one's trailing comment."""
    if value is None:
        if key in table:
            del table[key]
        return
    new = tomlkit.item(value)
    if key in table:
        old = table[key]
        with contextlib.suppress(AttributeError):
            new.trivia.comment = old.trivia.comment
            new.trivia.comment_ws = old.trivia.comment_ws
    table[key] = new


def _tidy_headers(text: str) -> str:
    """Exactly one blank line before each [section] / [[entry]] header (tomlkit's spacing of
    added tables varies). A header right under its own comment keeps the comment attached."""
    out: list[str] = []
    for line in text.split("\n"):
        if line.startswith("[") and out:
            while len(out) > 1 and out[-1] == "" and out[-2] == "":
                out.pop()                                  # no double blank lines
            if out[-1] != "" and not out[-1].lstrip().startswith("#"):
                out.append("")
        out.append(line)
    return "\n".join(out)


def _atomic_write(path: Path, text: str) -> None:
    """Write next to the file, then rename over it: readers see the old or the new file, never half."""
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        with contextlib.suppress(OSError):
            os.chmod(tmp, path.stat().st_mode & 0o777 if path.exists() else 0o644)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


class Settings:
    def __init__(self, path: Path, environ: dict[str, str] | None = None) -> None:
        self.path = Path(path)
        self.environ = dict(os.environ if environ is None else environ)
        self.locked = env_keys(self.environ)
        self._lock = asyncio.Lock()

    # --- reading ---

    def read(self) -> Files:
        text = self.path.read_text(encoding="utf-8")
        raw = tomlkit.parse(text)
        sources_file = (raw.get("location") or {}).get("sources_file")
        if ("location", "sources_file") in self.locked:
            sources_file = self.environ["ANCHORLESS__LOCATION__SOURCES_FILE"]
        local_path = resolve_local_path(self.path, str(sources_file)) if sources_file else None
        local_text = None
        if local_path:
            with contextlib.suppress(FileNotFoundError):
                local_text = local_path.read_text(encoding="utf-8")
        return Files(self.path, text, local_path, local_text)

    def parse(self, files: Files) -> Config:
        return parse_config(files.config_text, self.environ, path=files.config_path,
                            local_text=files.local_text if files.local_path else None)

    def snapshot(self) -> dict:
        """Everything the settings page shows."""
        files = self.read()
        cfg = self.parse(files)
        doc = tomlkit.parse(files.config_text)
        sections = []
        for sid, title, fields in SECTIONS:
            out = []
            for key, label, help_, applies in fields:
                section, field = key.split(".")
                value = _get(cfg, key)
                locked = "environment" if (section, field) in self.locked else None
                note = None
                if key == "breaking.sound" and value not in SOUNDS:
                    locked, note = "file", "SET IN THE FILE (A SOUND FILE) - CHANGE IT THERE"
                if applies == "file":
                    locked, note = "file", FILE_LOCK_NOTE
                out.append({"key": key, "label": label, "help": help_, "applies": applies,
                            "value": value, "locked": locked, "lock_note": note, **_schema(Config, key)})
            sections.append({"id": sid, "title": title, "fields": out})
        return {
            "version": files.version,
            "config_path": str(files.config_path),
            "local_path": str(files.local_path) if files.local_path else None,
            "sections": sections,
            "channels": self._channels(cfg),
            "segments": [s.model_dump(exclude_defaults=True) | {"name": s.name} for s in cfg.rundown.segment],
            "feeds": self._feeds(cfg, doc, files),
            "file_only": self._file_only(cfg),
            "classic_now": resolve_look("classic", datetime.now(UTC), cfg.tz),
            "themes": ["studio", "classic", "classic-light", "classic-dark"],
            "scopes": ["local", "national", "world"],
        }

    def _channels(self, cfg: Config) -> list[dict]:
        out = []
        for i, ch in enumerate([cfg.channel, *cfg.extra_channel]):
            locked = [f for f in CHANNEL_FIELDS if i == 0 and ("channel", f) in self.locked]
            look = resolve_look(ch.theme, datetime.now(UTC), cfg.tz)
            out.append({"main": i == 0, "id": ch.id, "theme": ch.theme, "look": look, "name": ch.name,
                        "show_on": ch.show_on, "channel_number": ch.channel_number, "locked": locked})
        return out

    def _feeds(self, cfg: Config, doc: Any, files: Files) -> list[dict]:
        # parse_config lists them in this order: built-in, then [[source]], then local.
        n_builtin = len(default_sources()) if cfg.feeds.builtin else 0
        n_config = len(doc.get("source") or [])
        out = []
        for i, s in enumerate(cfg.source):
            origin = "builtin" if i < n_builtin else "config" if i < n_builtin + n_config else "local"
            out.append({"origin": origin, "name": s.name, "url": s.url, "scope": s.scope,
                        "category": s.category, "enabled": s.enabled, "compressed": s.compressed})
        if not cfg.feeds.builtin:          # still list the built-ins, as off
            listed = {f["url"] for f in out}
            out = [{"origin": "builtin", "name": s.name, "url": s.url, "scope": s.scope,
                    "category": s.category, "enabled": False, "compressed": True}
                   for s in default_sources() if s.url not in listed] + out
        return out

    def _file_only(self, cfg: Config) -> dict:
        out = {}
        for section, keys in FILE_ONLY.items():
            values = getattr(cfg, section).model_dump()
            if keys:
                values = {k: values[k] for k in keys}
            out[section] = values
        out["admin"]["password"] = "set" if cfg.admin.password else "not set"
        out["admin"]["password_hash"] = "set" if cfg.admin.password_hash else "not set"
        out["breaking"] = {"sound file": cfg.breaking.sound} if cfg.breaking.sound not in SOUNDS else {}
        return {k: v for k, v in out.items() if v}

    # --- writing ---

    async def patch(self, ops: list[dict]) -> Config:
        """Apply the page's changes to the files. Raises Conflict, Invalid or SettingsError."""
        if not ops:
            raise SettingsError("nothing to change")
        async with self._lock:
            files = self.read()
            current = self.parse(files)
            doc = tomlkit.parse(files.config_text)
            local_doc = tomlkit.parse(files.local_text) if files.local_text is not None else None
            conflicts: list[str] = []
            for op in ops:
                local_doc = self._apply(op, current, doc, local_doc, conflicts)
            if conflicts:
                raise Conflict(conflicts)
            new_config = _tidy_headers(tomlkit.dumps(doc))
            new_local = _tidy_headers(tomlkit.dumps(local_doc)) if local_doc is not None else None
            # Where the local feeds file is (it may have just been named).
            sources_file = (doc.get("location") or {}).get("sources_file")
            local_path = resolve_local_path(self.path, str(sources_file)) if sources_file else files.local_path
            try:
                cfg = parse_config(new_config, self.environ, path=self.path,
                                   local_text=new_local if local_path else None)
            except ConfigError as err:
                raise Invalid(str(err)) from err
            if local_path and new_local is not None and new_local != (files.local_text or ""):
                _atomic_write(local_path, new_local)
            if new_config != files.config_text:
                _atomic_write(self.path, new_config)
            return cfg

    def _check(self, key: str, loaded: Any, now: Any, conflicts: list[str]) -> None:
        if loaded != now:
            conflicts.append(key)

    def _apply(self, op: dict, cur: Config, doc: Any, local_doc: Any, conflicts: list[str]) -> Any:
        kind = op.get("op")
        if kind == "set":
            key = op["key"]
            if key not in SCALAR_KEYS:
                raise SettingsError(f"{key} can only be changed in the file")
            section, field = key.split(".")
            if (section, field) in self.locked:
                raise SettingsError(f"{key} is set by the environment")
            value = op.get("value")
            if key == "breaking.sound" and value not in SOUNDS:
                raise SettingsError("the alert sound must be one of " + ", ".join(SOUNDS))
            self._check(key, op.get("old"), _get(cur, key), conflicts)
            _set(_table(doc, section), field, value)
        elif kind == "channel":                       # change one channel's fields
            cid, values, old = op["id"], op.get("value") or {}, op.get("old") or {}
            chans = {c.id: c for c in [cur.channel, *cur.extra_channel]}
            if cid not in chans:
                conflicts.append(f"channel {cid}")
                return local_doc
            ch = chans[cid]
            for f in values:
                if f not in CHANNEL_FIELDS:
                    raise SettingsError(f"channel field {f} can only be changed in the file")
                if ch is cur.channel and ("channel", f) in self.locked:
                    raise SettingsError(f"channel {f} is set by the environment")
                if f in old:
                    self._check(f"{ch.name} {f}", old[f], getattr(ch, f), conflicts)
            if ch is cur.channel:
                table = _table(doc, "channel")
            else:
                table = next(t for t in _aot(doc, "extra_channel") if _channel_id(t) == cid)
                if "name" in values and "id" not in table:   # keep its id (the stream URL) when renamed
                    table["id"] = cid
            for f, v in values.items():
                _set(table, f, int(v) if f == "channel_number" and str(v).isdigit() else v)
        elif kind == "add_channel":
            v = {k: x for k, x in (op.get("value") or {}).items() if k in CHANNEL_FIELDS and x not in (None, "")}
            t = tomlkit.table()
            for k in CHANNEL_FIELDS:
                if k in v:
                    t[k] = int(v[k]) if k == "channel_number" and str(v[k]).isdigit() else v[k]
            _append(_aot(doc, "extra_channel", create=True), t)
        elif kind == "remove_channel":
            aot = _aot(doc, "extra_channel")
            idx = [i for i, t in enumerate(aot or []) if _channel_id(t) == op["id"]]
            if not idx:
                conflicts.append(f"channel {op['id']}")
                return local_doc
            del aot[idx[0]]
            if not len(aot):
                del doc["extra_channel"]
        elif kind == "segments":                      # the whole list, in order
            old = op.get("old")
            now = [s.model_dump(exclude_defaults=True) | {"name": s.name} for s in cur.rundown.segment]
            self._check("segments", old, now, conflicts)
            aot = tomlkit.aot()
            for seg in op.get("value") or []:
                t = tomlkit.table()
                t["name"] = seg["name"]
                t["stories"] = int(seg.get("stories", 3))
                for k in ("scope", "category"):
                    if seg.get(k):
                        t[k] = seg[k]
                if seg.get("exclude_scope"):
                    t["exclude_scope"] = list(seg["exclude_scope"])
                aot.append(t)
            rundown = _table(doc, "rundown")
            if "segment" in rundown:
                del rundown["segment"]
            _blank_line(rundown)
            rundown.append("segment", aot)
        elif kind in ("feed_toggle", "feed_edit", "feed_remove", "feed_add"):
            local_doc = self._feed(op, cur, doc, local_doc, conflicts)
        else:
            raise SettingsError(f"unknown change {kind!r}")
        return local_doc

    def _feed(self, op: dict, cur: Config, doc: Any, local_doc: Any, conflicts: list[str]) -> Any:
        kind, origin = op["op"], op.get("origin")
        if origin not in ("builtin", "config", "local"):
            raise SettingsError("feed origin must be builtin, config or local")
        url = op.get("url")
        if origin == "local" and local_doc is None:
            if kind != "feed_add":
                conflicts.append(f"feed {url}")
                return local_doc
            # The first local feed: start a local feeds file next to the config.
            local_doc = tomlkit.document()
            local_doc.add(tomlkit.comment("Local outlets' feeds (Anchorless [location] sources_file)."))
            _set(_table(doc, "location"), "sources_file", "local.toml")
        target = local_doc if origin == "local" else doc
        current = {s.url: s for s in cur.source}
        if kind == "feed_toggle":
            if url not in current and not (origin == "builtin" and not cur.feeds.builtin):
                conflicts.append(f"feed {url}")
                return local_doc
            if url in current:
                self._check(f"feed {current[url].name}", op.get("old"), current[url].enabled, conflicts)
            on = bool(op.get("value"))
            if origin == "builtin":
                feeds = _table(doc, "feeds")
                disabled = [u for u in (feeds.get("disabled") or []) if u != url]
                if not on:
                    disabled.append(url)
                _set(feeds, "disabled", disabled or None)
                if on and not cur.feeds.builtin:
                    raise SettingsError("turn the built-in feeds on first")
            else:
                entry = next((t for t in (_aot(target, "source") or []) if t.get("url") == url), None)
                if entry is None:
                    conflicts.append(f"feed {url}")
                    return local_doc
                _set(entry, "enabled", None if on else False)
            return local_doc
        if origin == "builtin":
            raise SettingsError("built-in feeds can only be turned on or off")
        value = op.get("value") or {}
        if kind in ("feed_add", "feed_edit"):
            new_url = str(value.get("url", "")).strip()
            if not new_url.startswith(("http://", "https://")):
                raise SettingsError("a feed URL must start with http:// or https://")
            if not str(value.get("name", "")).strip():
                raise SettingsError("a feed needs a name")
            if new_url != url and new_url in current:
                raise SettingsError("that feed is already in the list")
        if kind == "feed_add":
            t = tomlkit.table()
            t["name"] = str(value["name"]).strip()
            t["url"] = new_url
            if origin != "local":
                t["scope"] = value.get("scope") or "national"
            if value.get("category") and value["category"] != "general":
                t["category"] = value["category"]
            if value.get("compressed") is False:
                t["compressed"] = False
            _append(_aot(target, "source", create=True), t)
            return local_doc
        aot = _aot(target, "source")
        idx = [i for i, t in enumerate(aot or []) if t.get("url") == url]
        if not idx:
            conflicts.append(f"feed {url}")
            return local_doc
        if kind == "feed_remove":
            del aot[idx[0]]
            return local_doc
        entry = aot[idx[0]]
        old = op.get("old") or {}
        src = current.get(url)
        for f in ("name", "url", "scope", "category"):
            if f in old and src is not None:
                self._check(f"feed {src.name} {f}", old[f], getattr(src, f), conflicts)
        _set(entry, "name", str(value["name"]).strip())
        _set(entry, "url", new_url)
        if origin != "local" and value.get("scope"):
            _set(entry, "scope", value["scope"])
        if "category" in value:
            _set(entry, "category", value["category"] if value["category"] not in ("", "general") else None)
        return local_doc


# --- what changed, and a record of it ---

def _feed_text(s: Any) -> str:
    return f"{s.name} ({s.scope}{', ' + s.category if s.category != 'general' else ''}){'' if s.enabled else ', off'}"


def _flat(cfg: Config) -> dict[str, Any]:
    """Every setting as "where: value", readable in a change list."""
    out: dict[str, Any] = {}
    data = cfg.model_dump(mode="json")
    for section, value in data.items():
        if section in ("source", "extra_channel"):
            continue
        if isinstance(value, dict):
            for key, v in value.items():
                if (section, key) == ("feeds", "disabled"):
                    continue        # shown per feed ("feed <url>: ... off") instead
                if section == "admin" and key in ("password", "password_hash"):
                    v = hashlib.sha256(str(v).encode()).hexdigest() if v else None   # changed or not, never the value
                if section == "rundown" and key == "segment":
                    v = ", ".join(f"{s['name']} {s['stories']}" for s in v)
                out[f"{section}.{key}"] = v
    for ch in cfg.extra_channel:
        for f in CHANNEL_FIELDS:
            out[f"channel {ch.id}.{f}"] = getattr(ch, f)
    for s in cfg.source:
        out[f"feed {s.url}"] = _feed_text(s)
    return out


def diff_configs(old: Config, new: Config) -> list[dict]:
    """[{key, old, new}] for every setting that differs (password values never included)."""
    a, b = _flat(old), _flat(new)
    out = []
    for key in sorted(a.keys() | b.keys()):
        if a.get(key) == b.get(key):
            continue
        if key in ("admin.password", "admin.password_hash"):
            out.append({"key": key, "old": "set" if a.get(key) else "not set",
                        "new": "changed" if a.get(key) and b.get(key) else ("set" if b.get(key) else "not set")})
        else:
            out.append({"key": key, "old": a.get(key), "new": b.get(key)})
    return out


class History:
    """settings-history.jsonl in the data folder: the last few hundred saves and hand edits."""

    KEEP = 500

    def __init__(self, path: Path) -> None:
        self.path = path

    def add(self, source: str, changes: list[dict]) -> None:
        if not changes:
            return
        line = json.dumps({"when": datetime.now(UTC).isoformat(timespec="seconds"), "source": source,
                           "changes": changes}, default=str)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
            lines = self.path.read_text(encoding="utf-8").splitlines()
            if len(lines) > self.KEEP + 100:            # trim now and then, not on every save
                _atomic_write(self.path, "\n".join(lines[-self.KEEP:]) + "\n")
        except OSError as err:
            log.warning("could not record settings history: %s", err)

    def recent(self, n: int = 20) -> list[dict]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()[-n:]
        except FileNotFoundError:
            return []
        out = []
        for line in reversed(lines):
            with contextlib.suppress(ValueError):
                out.append(json.loads(line))
        return out
