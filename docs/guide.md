# Anchorless guide

Everything beyond the [README](../README.md): running it, the TV tuner, themes and
channels, the settings page, hosting publicly, and configuration.

## Watch in a browser

Open `http://<host>:9798/` for a viewer and status page: the live channel
(full screen with `F` or a double-click), the current rundown, breaking alerts,
and which feeds are working. It is read-only; watching from it starts and stops
the encoder like any other viewer. (The player is
[mpegts.js](https://github.com/xqq/mpegts.js), Apache-2.0, bundled.)

## Running it and adding it to your TV

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
- `classic-light`: full-screen cable-news pages in blue.
- `classic-dark`: the same pages in charcoal and near-black.
- `classic`: light by day (6:00-19:00 local), dark at night.

The web pages take the look of the channel you watch (the settings page: the
main channel's).

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

## Which headline is shown

When several outlets carry the same story, Anchorless shows one headline. By
default that is the first-published version. With `[rundown] headline_choice =
"consensus"`, that version is replaced only when it has a red flag - an
editorializing word no other outlet uses ("slams", "meltdown"...), shouting in
capitals, an exclamation mark, or wording almost none of the other outlets share
(words and "!" inside quotation marks are someone's quote, so they don't count) -
and another version is clean, at least as complete, and clearly better by
`headline_margin`. No outlet is named or rated anywhere: the choice comes only from
what the outlets wrote. `"log"` (the default) keeps the first-published headline
and lists what consensus would change on the settings page, so you can judge it
before switching it on. `anchorless headlines` shows every version and its score.

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

It is **off until a password is set** (12+ characters): `ANCHORLESS__ADMIN__PASSWORD`
in the environment, or a hash in the config from `anchorless hash-password`
(`[admin] password_hash`, scrypt) so the file never holds the password itself.
Every change, from the page or a hand edit, is recorded with who/what/when
(`data/settings-history.jsonl`, shown on the page under "Recent changes").
The pages send their own security headers (a strict Content-Security-Policy, no
framing of the settings page, `nosniff`), so they are safe without a reverse proxy too. It is on the same port as everything else; only `/settings` and
its API need the login (the TV tuner, guide and viewer page stay open). By
default it only answers private networks (`[admin] allow_from`) and only over
https (`[admin] require_https`: put it behind a reverse proxy with TLS, or use
it from the server itself). Paths, the video encoder and the server settings
stay file-only.

Feeds are fetched by the server, so every feed request - redirects included -
must go to a public address: a URL can't point it at your router or other
services on your network (`[feeds] allow_private = true` allows it).

## Hosting publicly

**Recommended: keep Anchorless private** - on your home network, or reachable
only through a VPN such as Tailscale or WireGuard. That is what it is built and
tested for.

If you do put it on the internet, the TV side (`/playlist.m3u`, `/guide.xml`,
`/live.ts`, `/hls/`) and the viewer page stay **open by design**: anyone who can
reach them can watch, and every channel someone watches costs about 30% of a CPU
core. The viewer limits below are how you cap that. Before you open it up:

- [ ] **TLS in front.** Run it behind a reverse proxy with https (Caddy, nginx,
      Traefik) and don't expose port 9798 itself: publish it to the proxy only
      (e.g. `127.0.0.1:9798:9798` in Docker, or a shared Docker network).
- [ ] **Tell it about the proxy:** `[admin] trusted_proxies = ["<proxy address>"]`,
      so the login, the viewer limits and the logs see real client addresses
      (`X-Forwarded-For` is ignored from anyone else).
- [ ] **Keep the settings page private.** Leave `[admin] allow_from` at its
      default (private networks only), leave `[admin] require_https = true`, and
      use a long random password - ideally as `[admin] password_hash` from
      `anchorless hash-password`. Or set no password at all: then there is no
      settings page.
- [ ] **https for the viewer page:** `[web] require_https = true`.
- [ ] **Set the limits** in `[stream]`: `max_sessions` (channels encoding at
      once; default 2), `max_viewers` (total), and `max_viewers_per_client` so one
      address can't take every slot. Leave the last at -1 if a TV server such as
      Jellyfin sits in between - all its viewers come from its one address.
- [ ] **Decide what the status shows:** `[web] public_status = "summary"` lists
      only counts on `/health` and the viewer page, not your feeds. (Feed URLs and
      error details are never public either way.)
- [ ] **Mind your location.** Local news shows your city on screen, and local
      feeds name your area's outlets. Leave out `[location]` for a public channel
      if that matters to you.
- [ ] **Harden the container** as in `deploy/docker-compose.example.yml`: a
      non-root user, `read_only: true`, `cap_drop: [ALL]`,
      `no-new-privileges`, and memory and CPU limits.
- [ ] **Know how to report a problem:** see [SECURITY.md](../SECURITY.md).
- [ ] **Keep it updated:** `docker compose pull && docker compose up -d`
      picks up new releases, with security fixes in the base image, ffmpeg and
      the Python libraries. Watch the repository's releases to hear about them.

## Configuration

Copy [`config.example.toml`](../config.example.toml) to `config.toml`. In
`[channel]`, `theme`, `show_on` and (for a TV channel) `channel_number` are
required; everything else is optional, and every setting is documented there. Any setting can also come from the
environment as `ANCHORLESS__<SECTION>__<KEY>`
(e.g. `ANCHORLESS__VIDEO__ENCODER=vaapi`). Keep personal details such as your
location in the environment, not in the file.

## Docker

See [`deploy/docker-compose.example.yml`](../deploy/docker-compose.example.yml).
For hardware encoding, pass `/dev/dri` through and add the host's `render`
group.

Images are published to `ghcr.io/gabebecker2048/anchorless` for amd64 and arm64:
`latest` is the newest release, `0.1` the newest 0.1.x, `0.1.0` exactly that
release. To build your own instead, swap `image:` for `build: ..` in the compose
file and run `docker compose build --pull` from a checkout.

## Sources and fair use

The default sources are major outlets' public RSS feeds. Anchorless shows only
what the feeds publish for display: headlines, short summaries and the outlet's
name. It never shows article text. Each outlet's feed terms apply to how you
use its feed; many allow personal, non-commercial use only. Add your own feeds
with `[[source]]`, turn any off with `[feeds] disabled`, or leave out the
built-in list with `[feeds] builtin = false`.
