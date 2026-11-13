---
title: Hosting publicly
---

**Recommended: keep Anchorless private**: on your home network, or reachable
only through a VPN such as Tailscale or WireGuard. That is what it is built and
tested for.

If you do put it on the internet, the TV side (`/playlist.m3u`, `/guide.xml`,
`/live.ts`, `/hls/`) and the viewer page stay **open by design**: anyone who can
reach them can watch, and every channel someone watches costs about 30% of a CPU
core. The viewer limits are how you cap that.

## Checklist

Before you open it up:

- [ ] **TLS in front.** Run it behind a reverse proxy with https (Caddy, nginx,
      Traefik) and don't expose port 9798 itself: publish it to the proxy only
      (e.g. `127.0.0.1:9798:9798` in Docker, or a shared Docker network).
- [ ] **Tell it about the proxy:** `[admin] trusted_proxies = ["<proxy address>"]`,
      so the login, the viewer limits and the logs see real client addresses
      (`X-Forwarded-For` is ignored from anyone else).
- [ ] **Keep the settings page private.** Leave `[admin] allow_from` at its
      default (private networks only), leave `[admin] require_https = true`, and
      use a long random password, ideally as `[admin] password_hash` from
      `anchorless hash-password`. Or set no password at all: then there is no
      settings page.
- [ ] **https for the viewer page:** `[web] require_https = true`.
- [ ] **Set the limits** in `[stream]`: `max_sessions` (channels encoding at
      once; default 2), `max_viewers` (total), and `max_viewers_per_client` so one
      address can't take every slot. Leave the last at `-1` if a TV server such as
      Jellyfin sits in between: all its viewers come from its one address.
- [ ] **Decide what the status shows:** `[web] public_status = "summary"` lists
      only counts on `/health` and the viewer page, not your feeds. (Feed URLs and
      error details are never public either way.)
- [ ] **Mind your location.** Local news shows your city on screen, and local
      feeds name your area's outlets. Leave out `[location]` for a public channel
      if that matters to you.
- [ ] **Harden the container** as in the [example compose file](install.html#docker):
      a non-root user, `read_only: true`, `cap_drop: [ALL]`, `no-new-privileges`,
      and memory and CPU limits.
- [ ] **Know how to report a problem:** see below.
- [ ] **Keep it updated:** `docker compose pull && docker compose up -d`
      picks up new releases, with security fixes in the base image, ffmpeg and
      the Python libraries. Watch the repository's releases to hear about them.

## Example: Caddy

```
news.example.com {
    reverse_proxy 127.0.0.1:9798
}
```

```toml
[admin]
trusted_proxies = ["127.0.0.1"]   # where the proxy connects from (see below)

[web]
require_https = true
public_status = "summary"

[stream]
max_sessions = 2
max_viewers = 10
max_viewers_per_client = 2
```

`trusted_proxies` is the address Anchorless sees the proxy connect from:
`127.0.0.1` when both run on the same machine outside Docker. If Anchorless runs
in Docker, it is the proxy's address on the Docker network (or the network's
gateway, for a proxy on the host).

## What Anchorless does on its own

- The web pages send their own security headers (a strict Content-Security-Policy,
  no framing of the settings page, `nosniff`), so they are safe without a proxy too.
- Feeds can only be fetched from public addresses (redirects included), so a URL
  typed into the settings page can't reach your router or other services on your
  network, unless you set `[feeds] allow_private = true`.
- The settings login waits after five wrong passwords a minute from one address.

## Reporting a vulnerability

Please report security problems **privately**, not in a public issue: use the
**Report a vulnerability** button on the repository's
[Security tab](https://github.com/GabeBecker2048/anchorless/security). What
counts, and what is by design, is in
[SECURITY.md](https://github.com/GabeBecker2048/anchorless/blob/main/SECURITY.md).
