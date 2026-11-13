---
title: Troubleshooting
---

First steps for almost anything:

- **Look at the log:** `docker compose logs -f anchorless`, or the terminal
  running `anchorless serve`. Add `-v` for more detail.
- **Check the config:** `anchorless check-config`.
- **Check the feeds:** `anchorless fetch`, or the **Feeds** card on the viewer page.

## Feeds

**A feed shows an error.**

| Error | Try |
|---|---|
| `ReadTimeout` / `ConnectTimeout`, every time | Add `compressed = false` to that source: some servers hang on compressed requests. |
| `HTTPStatusError: 403` | The site blocks feed readers. Look for another feed from the same outlet. |
| `HTTPStatusError: 404` | The feed moved. Find its new address ([how](local-news.html#2-find-your-outlets-feeds)). |
| `HTTPStatusError: 429` | Too many requests. Anchorless already spaces out feeds from one site; raise `refresh_minutes` or use fewer feeds from that site. |
| `... is on a private network ...` | The feed (or a redirect) points at your own network. See [`allow_private`](feeds.html#feeds-on-your-own-network). |

A failing feed keeps showing its last stories until they age out, so one bad
feed never empties the screen.

**A feed works but none of its stories show up.** They may be older than
`max_story_age_hours`, filtered by `exclude`, already shown in an earlier
segment, or crowded out by better-ranked stories. `anchorless fetch` shows the
whole rundown.

**National stories in the local segment.** Use the outlet's local-section feed,
or add `exclude` patterns. See [Local news](local-news.html#tuning).

## Config errors

| Message | Means |
|---|---|
| `Extra inputs are not permitted` | A misspelled or unknown setting. Check the name in the [reference](configuration.html). |
| `settings that moved: ...` | An old setting name; the message gives the new one. |
| `no enabled feeds` | Every feed is off, or `builtin = false` with no `[[source]]`. |
| `local sources file not found` | `sources_file` is relative to `config.toml`'s folder. In Docker, put it in `./config`. |
| `channel_number is required` | A channel with `show_on = "both"` or `"tv"` needs a number. |
| `two TV channels have the same channel_number` / `channel ids must be unique` | Give each channel its own number, and its own `name` or `id`. |
| `unknown timezone` | Use a tz database name, e.g. `America/New_York`. |
| `expected ANCHORLESS__<SECTION>__<KEY>` | An environment variable with the wrong shape: two underscores between parts. |

A broken edit while it's running doesn't stop the station: it keeps the last
good config and logs the error.

## Docker

**`Permission denied` writing `/config` or `/data`.** The folders must belong to
the `user:` in your compose file. Create them yourself before the first start
(`mkdir config data`), and set `user:` to your `id -u`:`id -g`. If Docker
already created them as root: `sudo chown -R $(id -u):$(id -g) config data`.

**The settings page can't save.** Mount the config *folder* (`./config:/config`),
not the file alone, and check its owner as above.

## Watching

**Black screen for a while before the picture starts.** Some TVs (Samsung in
particular) buffer about 10 seconds first. Keep `[stream] lead_seconds` at 10.

**Jellyfin stutters, or starts slowly for the second viewer.** Turn off
**Allow stream sharing** on the M3U tuner. See [Jellyfin](watching.html#jellyfin).

**"BUSY", or HTTP 503.** A viewer limit was reached: by default two channels can
be on at once. See [Viewer limits](performance.html#viewer-limits).

**The channel doesn't appear in my TV app.** Check its `show_on` is `"both"` or
`"tv"`, then refresh the tuner and guide in the app. Open
`http://<host>:9798/playlist.m3u` in a browser to see what's listed.

**The guide shows the wrong times.** Set `[channel] timezone`.

**No music.** Music needs MP3 files in `[audio] music_dir` (in Docker, a folder
mounted at `/music`). Anchorless ships none. The log says how many tracks a
channel found when it starts.

## Settings page

| It says | Do |
|---|---|
| SETTINGS ARE OFF | Set a password and restart. See [Turning it on](settings-page.html#turning-it-on). |
| USE HTTPS | Open it through your https address, or on the server itself, or set `[admin] require_https = false` on a network you trust. |
| NOT ALLOWED | Your address isn't in `[admin] allow_from`. Behind a reverse proxy, set `trusted_proxies`. |
| A setting is locked | It's set by an environment variable, or it's [file only](settings-page.html#file-only). |
| Conflict | Someone (or a hand edit) changed that setting since you loaded the page. Reload and try again. |

## Still stuck?

[Open an issue](https://github.com/GabeBecker2048/anchorless/issues) with your
version (`anchorless --version`), how you run it, and the relevant log lines.
Leave out your location and local feeds if you'd rather not share them.
