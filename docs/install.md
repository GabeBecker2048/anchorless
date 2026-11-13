---
title: Install
---

Anchorless runs as a Docker container, or natively with Python 3.12+ and ffmpeg.
Either way, the first start writes a `config.toml` with every setting explained,
and the defaults work: you get a national and world newscast straight away.

## Docker

Save this as `docker-compose.yml` in a new folder:

```yaml
services:
  anchorless:
    image: ghcr.io/gabebecker2048/anchorless:latest   # or :1 to stay on 1.x
    restart: unless-stopped
    user: "1000:1000"            # who owns ./config and ./data (`id -u`:`id -g`)
    ports:
      - "9798:9798"
    volumes:
      - ./config:/config         # config.toml: written on first start, edit it any time
      - ./data:/data
      # - /path/to/music:/music:ro    # a folder of MP3s to play underneath
    # environment:
    #   ANCHORLESS__LOCATION__CITY: Springfield    # local news (see config.toml)
    #   ANCHORLESS__ADMIN__PASSWORD: <long random> # turns on the settings page
    # Hardware encoding (Intel/AMD): uncomment, set the host's render group id
    # (getent group render), and set encoder = "vaapi" in config.toml.
    # devices: ["/dev/dri:/dev/dri"]
    # group_add: ["992"]
    # Hardening: Anchorless only writes to /config, /data and /tmp.
    read_only: true
    tmpfs: [/tmp]
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    mem_limit: 512m
```

Then, in that folder:

```sh
mkdir config data      # so they're yours, not root's
docker compose up -d
```

- The first start writes `config/config.toml`. Edit it any time; most changes
  apply within seconds (see [Settings page](settings-page.html) for which need a restart).
- `user:` must match the owner of `./config` and `./data` (`id -u` and `id -g`).
- Uncomment the `/music` volume line to play your own MP3s underneath (see [Music](newscast.html#music)).
- Uncomment `environment:` for [local news](local-news.html) and the [settings page](settings-page.html).
- Hardware encoding (Intel/AMD GPUs): see [Performance](performance.html#hardware-encoding).

Run any [command](cli.html) inside the container with
`docker compose exec anchorless anchorless <command>`, for example
`docker compose exec anchorless anchorless fetch`.

### Image tags

Images are published to `ghcr.io/gabebecker2048/anchorless` for amd64 and arm64.

| Tag | What you get |
|---|---|
| `latest` | the newest release |
| `1` | the newest 1.x: new features and fixes, no breaking changes |
| `1.0` | the newest 1.0.x: fixes only |
| `1.0.2` | exactly that release |

To build the image yourself, replace `image:` with `build: <path to a checkout>`.

## Native (pip or uv)

```sh
pip install anchorless   # or: uv tool install anchorless
anchorless init          # writes config.toml (and local.example.toml) here
anchorless serve
```

ffmpeg must be on the `PATH` (`apt install ffmpeg`, `brew install ffmpeg`, ...).

Run `anchorless serve` from the folder with `config.toml`, or point at the file
with `anchorless -c /path/to/config.toml serve` (or the `ANCHORLESS_CONFIG`
environment variable). The story database goes in `data/` next to the config file.

To keep it running, use whatever runs your other services: a systemd unit, a
`tmux` session, or the Docker image.

## Check it works

1. Open `http://<host>:9798/` in a browser and press **Watch live**.
2. The **Feeds** card on that page shows which feeds are working.
3. Then add it to your TV: see [Watch it](watching.html).

`anchorless fetch` prints the current rundown in the terminal without starting
the stream, which is a quick way to test a config change.

## Updating

| Install | Update with |
|---|---|
| Docker | `docker compose pull && docker compose up -d` |
| pip | `pip install -U anchorless` |
| uv | `uv tool upgrade anchorless` |

Your `config.toml` is never overwritten. New settings get sensible defaults, so an
old config keeps working; if a setting was renamed, Anchorless tells you the new
name at start-up. What changed in each release is in the
[changelog](https://github.com/GabeBecker2048/anchorless/blob/main/CHANGELOG.md).
Watch the repository's releases on GitHub to hear about new versions.
