# Anchorless

**News without the anchor.** Anchorless turns news headlines into a 24/7 TV
channel. It is a looping newscast of text pages, with a headline crawl, a clock,
background music and breaking-news alerts. It serves the channel as a Live TV
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

## Quick start

```sh
uv sync
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

MIT. The bundled Barlow fonts are under the SIL Open Font License
(`src/anchorless/fonts/OFL-Barlow.txt`).
