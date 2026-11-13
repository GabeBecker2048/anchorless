# Anchorless

[![PyPI](https://img.shields.io/pypi/v/anchorless)](https://pypi.org/project/anchorless/)
[![Python versions](https://img.shields.io/pypi/pyversions/anchorless)](https://pypi.org/project/anchorless/)
[![Docker image](https://img.shields.io/badge/docker-ghcr.io-blue?logo=docker&logoColor=white)](https://github.com/GabeBecker2048/anchorless/pkgs/container/anchorless)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](https://github.com/GabeBecker2048/anchorless/blob/main/LICENSE)
[![CI](https://github.com/GabeBecker2048/anchorless/actions/workflows/test.yml/badge.svg)](https://github.com/GabeBecker2048/anchorless/actions/workflows/test.yml)

![The Studio look: an empty pixel-art news set. Headlines play on the big screen behind the desk, then a breaking-news alert turns the studio red](https://raw.githubusercontent.com/GabeBecker2048/anchorless/main/docs/studio.gif)

<sub>Recorded from the real playout, sped up. The headlines and outlets are made up.</sub>

**[Read the docs](https://gabebecker.com/anchorless/)**: install, local news, channels, every setting.

**News without the anchor.** Anchorless turns news headlines into a 24/7 TV
channel you can add to Jellyfin, Plex, Channels DVR or any IPTV player: an empty
pixel-art news set where the news plays on the big screen behind a desk nobody
sits at - with a headline crawl, background music and breaking-news alerts.

- Pulls headlines from public RSS feeds, groups the same story across outlets,
  and builds a rundown (top stories, local, national, world, business).
- Breaking news interrupts the rundown when many outlets pick a story up at once.
- Two looks: the pixel-art **Studio**, or **Classic** cable-news pages (light, dark,
  or switching with the time of day).
- Lightweight: no browser - Python draws the frames, ffmpeg encodes them, and
  nothing runs while nobody is watching.
- Watch it in a browser too, and change its settings there (optional, password
  protected).

## Install

Anchorless runs as a Docker container, or natively with Python 3.12+ and
[ffmpeg](https://ffmpeg.org/download.html).

### Docker

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

The first start writes `config/config.toml`, with every setting explained.
Update with `docker compose pull && docker compose up -d`.

### Native

```sh
pip install anchorless   # or: uv tool install anchorless
anchorless init          # writes config.toml here
anchorless serve
```

ffmpeg must be on the PATH (`apt install ffmpeg`, `brew install ffmpeg`, ...).
Run `anchorless serve` from the folder with `config.toml`, or point at it with
`anchorless -c /path/to/config.toml serve`.

### Watch

Open `http://<host>:9798/` to watch in a browser, or add it to Jellyfin, Plex or
any IPTV player as an M3U tuner (`http://<host>:9798/playlist.m3u`) with an
XMLTV guide (`http://<host>:9798/guide.xml`). Step by step for each app:
[Watch it](https://gabebecker.com/anchorless/watching.html).

## More

- [The docs](https://gabebecker.com/anchorless/): Jellyfin and other TV apps, local news, feeds,
  themes and channels, the settings page, hosting publicly, every setting
- [`config.example.toml`](https://github.com/GabeBecker2048/anchorless/blob/main/config.example.toml): every setting, explained (what `anchorless init` writes)
- [SECURITY.md](https://github.com/GabeBecker2048/anchorless/blob/main/SECURITY.md): reporting a vulnerability
- [CHANGELOG.md](https://github.com/GabeBecker2048/anchorless/blob/main/CHANGELOG.md): what changed in each release

Anchorless doesn't include music: point it at a folder of MP3s you have the
right to play (`[audio] music_dir`), or it runs with just its own sound effects.

## License

MIT. The bundled fonts are under the SIL Open Font License and the bundled
[mpegts.js](https://github.com/xqq/mpegts.js) player under Apache 2.0. Headlines
belong to their outlets; see [Sources and fair use](https://gabebecker.com/anchorless/feeds.html#sources-and-fair-use).
