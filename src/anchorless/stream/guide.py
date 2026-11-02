"""The M3U playlist and XMLTV guide that make the channels a Live TV tuner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from xml.sax.saxutils import escape, quoteattr

from ..config import Config

GUIDE_DAYS = 3


@dataclass(frozen=True)
class ChannelInfo:
    id: str
    number: str
    name: str
    theme: str
    path: str          # the stream's URL path


def channel_list(cfg: Config) -> list[ChannelInfo]:
    """The main channel, then any [[extra_channel]]s."""
    c = cfg.channel
    out = [ChannelInfo(c.id, c.number, c.name, cfg.theme.name, "/live.ts")]
    for x in cfg.extra_channel:
        out.append(ChannelInfo(x.id, x.number, x.name, x.theme, f"/live/{x.id}.ts"))
    return out


def playlist(cfg: Config, host: str) -> str:
    lines = ["#EXTM3U"]
    for ch in channel_list(cfg):
        lines.append(f'#EXTINF:-1 tvg-id="{ch.id}" tvg-chno="{ch.number}" tvg-name="{ch.name}",{ch.name}')
        lines.append(f"http://{host}{ch.path}")
    return "\n".join(lines) + "\n"


def _xmltv_time(d: datetime) -> str:
    return d.strftime("%Y%m%d%H%M%S %z")


def guide(cfg: Config, now: datetime) -> str:
    """One programme per local day (midnight to midnight, DST-aware) on every channel."""
    c = cfg.channel
    tz = cfg.tz
    today = now.astimezone(tz).date()
    channels = channel_list(cfg)
    out = ['<?xml version="1.0" encoding="UTF-8"?>', "<tv>"]
    for ch in channels:
        out.append(f"  <channel id={quoteattr(ch.id)}><display-name>{escape(ch.name)}</display-name></channel>")
    for ch in channels:
        for i in range(GUIDE_DAYS):
            day = today + timedelta(days=i)
            start = datetime(day.year, day.month, day.day, tzinfo=tz)
            nxt = day + timedelta(days=1)
            stop = datetime(nxt.year, nxt.month, nxt.day, tzinfo=tz)
            out.append(f"  <programme start=\"{_xmltv_time(start)}\" stop=\"{_xmltv_time(stop)}\" "
                       f"channel={quoteattr(ch.id)}><title lang=\"en\">{escape(c.guide_title)}</title>"
                       f"<desc lang=\"en\">{escape(c.guide_description)}</desc>"
                       f"<category lang=\"en\">News</category></programme>")
    out.append("</tv>")
    return "\n".join(out) + "\n"
