# Anchorless

![The Studio look: an empty pixel-art news set. Headlines play on the big screen behind the desk, then a breaking-news alert turns the studio red](docs/studio.gif)

<sub>Recorded from the real playout (sped up: pages normally stay 12 s). The headlines and outlets are made up.</sub>

**News without the anchor.** Anchorless turns news headlines into a 24/7 TV
channel: an empty pixel-art news set, where the news plays on the big screen
behind a desk nobody sits at. There is a headline crawl, a clock, background
music and breaking-news alerts (the studio goes red and the desk beacon spins).
The window behind the set follows the time of day, and there are fish. It serves the channel as a Live TV
tuner (M3U + XMLTV + MPEG-TS) for Jellyfin, Plex, Channels DVR or any IPTV
player.

- **Lightweight:** Python draws every frame with Pillow; no browser. Drawing
  costs about 1 % of a CPU core; encoding is hardware (VA-API) or x264.
- **On demand:** news is fetched all the time (cheap). Drawing and encoding run
  only while someone watches, and stop a minute after the last viewer leaves.
- **Fast tune-in:** 10 s of video is rendered ahead at once, so TV players that
  buffer before showing anything start quickly. Viewers who join a running
  stream get the same head start.
- **A real rundown:** stories from many outlets are grouped (the same story from
  six outlets is one story, credited to all six) and ranked by freshness and
  coverage. Then they fill segments you define: TOP STORIES, NATIONAL, WORLD,
  BUSINESS...
- **Breaking news:** a story that 4+ outlets pick up within 30 minutes (or that
  is marked "BREAKING:") interrupts the rundown at the next page. It gets a full
  alert, and then a red tag in the crawl.

## Watch in a browser

Open `http://<host>:9798/` for a viewer and status page: the live channel
(full screen with `F` or a double-click), the current rundown, breaking alerts,
and which feeds are working. It is read-only; watching from it starts and stops
the encoder like any other viewer. (The player is
[mpegts.js](https://github.com/xqq/mpegts.js), Apache-2.0, bundled.)

## Quick start

```sh
uv sync
cp config.example.toml config.toml # [channel] theme, show_on and channel_number are required
uv run anchorless fetch            # print the current rundown
uv run anchorless render -o out    # PNG stills of every page type
uv run anchorless preview -o out/preview.mp4 --seconds 60 --breaking
uv run anchorless serve            # the channel, on port 9798
```

Then point your IPTV client at:

| What | URL |
|---|---|
| Tuner (M3U) | `http://<host>:9798/playlist.m3u` |
| Guide (XMLTV) | `http://<host>:9798/guide.xml` |
| Status | `http://<host>:9798/health` |

**Jellyfin:** add an M3U tuner and an XMLTV guide with the URLs above.
**Turn off "Allow stream sharing"** on the tuner. Jellyfin starts a viewer who
joins a shared stream at its live edge, with nothing buffered. Without sharing,
every viewer gets Anchorless's own head start.

## Themes and channels

- `studio`: the empty pixel-art news set.
- `classic`: full-screen cable-news pages.

Every channel, `[channel]` and any number of `[[extra_channel]]`s, has the
same settings:

```toml
[channel]
theme = "studio"       # required
name = "NEWS"          # optional for [channel] (default "NEWS"), required for extra channels
show_on = "both"       # required: "both", "tv" (playlist + guide only) or "web" (web page only)
channel_number = 101   # required for "both" and "tv"; ignored for "web"
```

They all share one news fetch; each gets its own stream, drawn and encoded only
while someone watches it. `show_on` decides where a channel is *listed*: any
channel's stream URL still plays for whoever opens it.

## Settings page

`/settings` edits the config file from a browser: channels, the rundown and its
segments, breaking-news rules, the crawl, sound and music volume, the TV guide,
and feeds (on/off, add, edit, with a "check feed" button). **The file stays the
one source of truth**: a save rewrites only the lines that changed (comments and
layout kept), so you can keep editing it by hand too - hand edits show up on the
page within seconds. Most changes apply live; a change to a channel's look,
name, crawl or sound restarts that channel, either right away or once nobody is
watching. Two people saving at once can't overwrite each other: a setting
changed since your page loaded it is reported as a conflict instead.

It is **off until a password is set**: `ANCHORLESS__ADMIN__PASSWORD` in the
environment. It is on the same port as everything else; only `/settings` and
its API need the login (the TV tuner, guide and viewer page stay open). By
default it only answers private networks (`[admin] allow_from`). Paths, the
video encoder and the server settings stay file-only.

## Configuration

Copy [`config.example.toml`](config.example.toml) to `config.toml`. Every
setting is optional and documented there. Any setting can also come from the
environment as `ANCHORLESS__<SECTION>__<KEY>`
(e.g. `ANCHORLESS__VIDEO__ENCODER=vaapi`). Keep personal details such as your
location in the environment, not in the file.

## Docker

See [`deploy/docker-compose.example.yml`](deploy/docker-compose.example.yml).
For hardware encoding, pass `/dev/dri` through and add the host's `render`
group.

## Sources and fair use

The default sources are major outlets' public RSS feeds. Anchorless shows only
what the feeds publish for display: headlines, short summaries and the outlet's
name. It never shows article text. Each outlet's feed terms apply to how you
use its feed; many allow personal, non-commercial use only. You can replace the
sources list entirely in your config.

## License

MIT. The bundled fonts (Barlow, Pixelify Sans, Silkscreen, VT323 and
Press Start 2P) are all under the SIL Open Font License.
