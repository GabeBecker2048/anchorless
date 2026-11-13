---
title: Watch it
---

Everything is on one port, `9798` by default. Replace `<host>` with the address
of the machine running Anchorless.

| What | URL |
|---|---|
| Viewer and status page | `http://<host>:9798/` |
| Tuner playlist (M3U) | `http://<host>:9798/playlist.m3u` |
| TV guide (XMLTV) | `http://<host>:9798/guide.xml` |
| Main channel's stream (MPEG-TS) | `http://<host>:9798/live.ts` |
| An extra channel's stream | `http://<host>:9798/live/<id>.ts` |
| HLS stream (Safari, iPhone) | `http://<host>:9798/hls/<id>.m3u8` |
| Status (JSON) | `http://<host>:9798/health` |
| Settings page | `http://<host>:9798/settings` |

Nothing is drawn or encoded until someone tunes in. The first viewer starts the
channel (about 2 seconds); it stops a minute after the last viewer leaves.

## In a browser

Open `http://<host>:9798/` and press **Watch live**. The page also shows the
current rundown, recent breaking alerts and which feeds are working. With more
than one channel, pick one from the menu at the top.

| Key | Does |
|---|---|
| <kbd>Space</kbd> or <kbd>K</kbd> | watch / stop |
| <kbd>F</kbd> or double-click | full screen |
| <kbd>M</kbd> | mute |
| <kbd>↑</kbd> <kbd>↓</kbd> | volume |

It works on phones too: iPhones play the HLS version of the stream automatically.

## Jellyfin

1. **Dashboard → Live TV → Tuner devices → Add**: type **M3U Tuner**, file or URL
   `http://<host>:9798/playlist.m3u`.
2. **Turn off "Allow stream sharing"** on that tuner.
3. **TV guide data providers → Add → XMLTV**: `http://<host>:9798/guide.xml`.
4. Refresh the guide data. The channel shows up under Live TV.

> Why turn off stream sharing: a viewer who joins a shared stream starts at its
> live edge with nothing buffered, which stutters on many TVs. Without sharing,
> every viewer gets Anchorless's own head start (`lead_seconds`).
{: .warn }

If you use Jellyfin, leave `[stream] max_viewers_per_client` at `-1`: all
Jellyfin viewers reach Anchorless from Jellyfin's one address.

## Plex

**Settings → Live TV & DVR → Set up Plex DVR.** Plex only accepts network tuners
(HDHomeRun), not M3U playlists, so it needs a bridge such as
[xTeVe](https://github.com/xteve-project/xTeVe) or Threadfin in between: give the
bridge the playlist and guide URLs above, then add the bridge to Plex as a tuner.

## Channels DVR

**Settings → Sources → Add source → Custom Channels**: stream format
**MPEG-TS**, source URL `http://<host>:9798/playlist.m3u`, and XMLTV guide
`http://<host>:9798/guide.xml`.

## VLC, Kodi, TiviMate and other IPTV players

Any player that takes an M3U playlist works: add `http://<host>:9798/playlist.m3u`
(and the guide URL where the player asks for EPG/XMLTV). For a single channel,
open its stream URL directly, e.g. `http://<host>:9798/live.ts` in VLC.

## Which channels are listed where

Each channel's `show_on` decides where it is listed: `"both"` (TV playlist and
guide, and the web page), `"tv"` or `"web"`. A channel's stream URL still plays
for anyone who opens it. See [Looks and channels](channels.html).

## Tips

- **Samsung and some other TVs** buffer about 10 seconds before showing
  anything. Anchorless renders that much ahead for each new viewer
  (`[stream] lead_seconds = 10`); lowering it makes those TVs sit on a black
  screen longer.
- **"BUSY"** on the viewer page (or an HTTP 503 in a TV app) means a viewer
  limit was reached. See [Performance](performance.html#viewer-limits).
- Watching from outside your home network: see [Hosting publicly](hosting-publicly.html).
