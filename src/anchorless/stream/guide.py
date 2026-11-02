"""The M3U playlist and XMLTV guide that make the channels a Live TV tuner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from xml.sax.saxutils import escape, quoteattr

from ..config import Config

GUIDE_DAYS = 3


@dataclass(frozen=True)
class ChannelInfo:
    id: str
    number: str | None    # None for a web-only channel
    name: str
    theme: str
    path: str             # the stream's URL path
    show_on: str = "both"

    @property
    def on_tv(self) -> bool:
        """Listed in /playlist.m3u and /guide.xml."""
        return self.show_on in ("both", "tv")

    @property
    def on_web(self) -> bool:
        """Offered on the web page."""
        return self.show_on in ("both", "web")

    @property
    def label(self) -> str:
        return f"{self.number} {self.name}" if self.number else self.name


def channel_list(cfg: Config) -> list[ChannelInfo]:
    """The main channel, then any [[extra_channel]]s."""
    c = cfg.channel
    out = [ChannelInfo(c.id, c.channel_number, c.name, c.theme, "/live.ts", c.show_on)]
    for x in cfg.extra_channel:
        out.append(ChannelInfo(x.id, x.channel_number, x.name, x.theme, f"/live/{x.id}.ts", x.show_on))
    return out


def playlist(cfg: Config, host: str) -> str:
    lines = ["#EXTM3U"]
    for ch in channel_list(cfg):
        if not ch.on_tv:
            continue
        lines.append(f'#EXTINF:-1 tvg-id="{ch.id}" tvg-chno="{ch.number}" tvg-name="{ch.name}",{ch.name}')
        lines.append(f"http://{host}{ch.path}")
    return "\n".join(lines) + "\n"


def _xmltv_time(d: datetime) -> str:
    return d.strftime("%Y%m%d%H%M%S %z")


def _slots(cfg: Config, now: datetime) -> list[tuple[datetime, datetime]]:
    """Guide blocks of ``guide_slot_minutes`` on local clock boundaries (e.g. :00 and
    :30), from the start of today for ``GUIDE_DAYS``. Steps are added in UTC, so the
    blocks stay on the boundaries across a DST change."""
    tz = cfg.tz
    slot = timedelta(minutes=cfg.channel.guide_slot_minutes)
    if slot == timedelta(days=1):    # one programme per local day, midnight to midnight
        today = now.astimezone(tz).date()
        days = [today + timedelta(days=i) for i in range(GUIDE_DAYS + 1)]
        edges = [datetime(d.year, d.month, d.day, tzinfo=tz) for d in days]
        return list(zip(edges, edges[1:], strict=False))
    today = now.astimezone(tz).date()
    last = today + timedelta(days=GUIDE_DAYS)
    start = datetime(today.year, today.month, today.day, tzinfo=tz).astimezone(UTC)
    end = datetime(last.year, last.month, last.day, tzinfo=tz).astimezone(UTC)
    out = []
    t = start
    while t < end:
        out.append((t.astimezone(tz), (t + slot).astimezone(tz)))
        t += slot
    return out


def guide(cfg: Config, now: datetime) -> str:
    """The newscast in back-to-back blocks (see ``_slots``) on every channel."""
    c = cfg.channel
    channels = [ch for ch in channel_list(cfg) if ch.on_tv]
    slots = _slots(cfg, now)
    out = ['<?xml version="1.0" encoding="UTF-8"?>', "<tv>"]
    for ch in channels:
        out.append(f"  <channel id={quoteattr(ch.id)}><display-name>{escape(ch.name)}</display-name></channel>")
    for ch in channels:
        for start, stop in slots:
            out.append(f"  <programme start=\"{_xmltv_time(start)}\" stop=\"{_xmltv_time(stop)}\" "
                       f"channel={quoteattr(ch.id)}><title lang=\"en\">{escape(c.guide_title)}</title>"
                       f"<desc lang=\"en\">{escape(c.guide_description)}</desc>"
                       f"<category lang=\"en\">News</category></programme>")
    out.append("</tv>")
    return "\n".join(out) + "\n"
