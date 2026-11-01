"""The M3U playlist and XMLTV guide that make the channel a Live TV tuner."""

from __future__ import annotations

from datetime import datetime, timedelta
from xml.sax.saxutils import escape, quoteattr

from ..config import Config

GUIDE_DAYS = 3


def playlist(cfg: Config, host: str) -> str:
    c = cfg.channel
    return ("#EXTM3U\n"
            f'#EXTINF:-1 tvg-id="{c.id}" tvg-chno="{c.number}" tvg-name="{c.name}",{c.name}\n'
            f"http://{host}/live.ts\n")


def _xmltv_time(d: datetime) -> str:
    return d.strftime("%Y%m%d%H%M%S %z")


def guide(cfg: Config, now: datetime) -> str:
    """One programme per local day (midnight to midnight, DST-aware)."""
    c = cfg.channel
    tz = cfg.tz
    today = now.astimezone(tz).date()
    out = ['<?xml version="1.0" encoding="UTF-8"?>', "<tv>",
           f"  <channel id={quoteattr(c.id)}><display-name>{escape(c.name)}</display-name></channel>"]
    for i in range(GUIDE_DAYS):
        day = today + timedelta(days=i)
        start = datetime(day.year, day.month, day.day, tzinfo=tz)
        nxt = day + timedelta(days=1)
        stop = datetime(nxt.year, nxt.month, nxt.day, tzinfo=tz)
        out.append(f"  <programme start=\"{_xmltv_time(start)}\" stop=\"{_xmltv_time(stop)}\" "
                   f"channel={quoteattr(c.id)}><title lang=\"en\">{escape(c.guide_title)}</title>"
                   f"<desc lang=\"en\">{escape(c.guide_description)}</desc>"
                   f"<category lang=\"en\">News</category></programme>")
    out.append("</tv>")
    return "\n".join(out) + "\n"
