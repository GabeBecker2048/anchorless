---
title: Settings page
---

`http://<host>:9798/settings` changes Anchorless from a browser: channels, the
rundown and its segments, breaking news, the crawl, sound and music volume, the
TV guide, viewer limits, and feeds (switch, add, edit, and test with **Check
feed**).

**The config file stays the one source of truth.** A save rewrites only the
lines that changed, keeping your comments and layout, so you can keep editing
the file by hand too. Hand edits show up on the page within seconds.

## Turning it on

It is off until a password (12+ characters) is set. Either:

**From the environment** (simplest):

```yaml
# docker-compose.yml
    environment:
      ANCHORLESS__ADMIN__PASSWORD: <a long random password>
```

**Or as a hash in the config file**, so the file never holds the password itself:

```sh
anchorless hash-password
# Docker: docker compose exec anchorless anchorless hash-password
```

It asks for the password twice and prints a line to paste into `config.toml`:

```toml
[admin]
password_hash = "scrypt$..."
```

Set one or the other, not both. Then restart Anchorless. Changing the password
logs everyone out.

> In Docker, the settings page needs to write `config.toml`, so mount the
> config **folder** (`./config:/config`), not the single file, and make sure the
> container's `user:` owns it.
{: .tip }

## Who can open it

Only the settings page and its API need the login. The TV playlist, guide,
streams and viewer page stay open.

By default the settings page:

- **only answers private networks**: this machine, your LAN, and Tailscale-style
  addresses (`[admin] allow_from`);
- **only works over https** (`[admin] require_https = true`), so your password
  never travels unencrypted. Opening it on the server itself (`localhost`) is
  always allowed. Otherwise, put Anchorless behind a reverse proxy with TLS
  (Caddy, nginx, Traefik) and list it in `[admin] trusted_proxies`. On a home
  network you trust, `require_https = false` turns this off.

Logins last 30 days (`[admin] session_days`). After five wrong passwords in a
minute from one address, it waits before accepting more.

### What the page tells you

| You see | Means |
|---|---|
| **SETTINGS ARE OFF** | No password is set. See above. |
| **USE HTTPS** | You opened it over plain http from another machine. Use your https address, open it on the server, or set `require_https = false`. |
| **NOT ALLOWED** | Your address isn't in `[admin] allow_from`. |
| **NO CONFIG FILE** | Anchorless was started without a config file, so there's nothing to edit. |

## Saving changes

Change what you like, then **Save** (or **Discard**). The bar at the bottom
lists every pending change.

- **Most changes apply right away**: the rundown, breaking news, feeds, the
  guide, viewer limits.
- **Some restart a channel**: its look, name, the crawl, the alert sound, and
  the music volume (marked ↻). If someone is watching, you choose: restart it
  now (viewers reconnect in about 2 seconds), or when nobody is watching.
- **Two people saving at once can't overwrite each other.** A setting changed
  since your page loaded it (by someone else, or a hand edit) is reported as a
  conflict instead of being overwritten.
- A setting that comes from an environment variable is locked on the page: the
  environment always wins over the file.

## File only

Some settings are shown on the page but can only be changed in `config.toml`,
and apply after a restart:

- `[video]`: picture size, encoder and quality
- `[stream]` `host`, `port`, `lead_seconds`, `idle_seconds`
- `[audio]` `music_dir`, `bitrate`
- `[location]` `city`, `sources_file`
- `[admin]` `require_https`, `allow_from`, `trusted_proxies`, `session_days`,
  and the password (the page can't turn off its own protection)
- `[feeds]` `allow_private`
- `[data]`
- a custom alert sound file (`[breaking] sound` set to a path)

## History

Every change, from the page or a hand edit, is recorded with what changed, from
what, to what, and when. The page shows recent ones under **Recent changes**;
the full log is `data/settings-history.jsonl`.

The **Headline choices** card lists stories where the
[consensus headline](newscast.html#which-headline-is-shown) would differ from
(or, with `"consensus"` on, did replace) the first-published one.

## If you save something invalid

The page checks every change exactly as a start-up would and refuses to save a
config that wouldn't load. A broken **hand edit** doesn't stop the station
either: it keeps running the last good config and logs the error until you fix
the file.
