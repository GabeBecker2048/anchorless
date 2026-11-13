---
title: Configuration
---

Anchorless reads one TOML file, `config.toml`. `anchorless init` (or the
container's first start) writes it with every setting explained in comments.

Only `[channel]` `theme`, `show_on` and (for a TV channel) `channel_number` are
required. Everything else is optional: leave a setting out and it uses the
default listed here. Unknown settings are errors, so a typo never goes unnoticed.

## Where the file is

| Run as | File |
|---|---|
| Docker | `/config/config.toml` in the container (`./config/config.toml` on the host) |
| Native | `./config.toml`, or `anchorless -c <path> ...`, or `$ANCHORLESS_CONFIG` |

Paths in the file (`sources_file`, `[data] dir`) are relative to the file's folder.

Changes to the file are picked up within a few seconds, without a restart, except
the [file-only settings](settings-page.html#file-only). If an edit breaks the
file, Anchorless keeps running the last good config and logs the error.
`anchorless check-config` validates the file and prints the result (never the
password).

## Environment variables

Any single setting can come from the environment as
`ANCHORLESS__<SECTION>__<KEY>`, which overrides the file:

```sh
ANCHORLESS__LOCATION__CITY=Springfield
ANCHORLESS__ADMIN__PASSWORD=<a long random password>
ANCHORLESS__VIDEO__ENCODER=vaapi
ANCHORLESS__RUNDOWN__PAGE_SECONDS=15
```

Use this for anything personal (your city, the password), so `config.toml` can
be shared. Lists (`allow_from`, `disabled`, segments, feeds) can only be set in
the file. `ANCHORLESS_CONFIG` (one underscore) sets the config file's path.

## `[channel]`

The main channel. Its clock and guide settings apply to every channel.
See [Looks and channels](channels.html).

| Key | Default | |
|---|---|---|
| `theme` | *(required)* | `"studio"`, `"classic"`, `"classic-light"` or `"classic-dark"` |
| `show_on` | *(required)* | `"both"`, `"tv"` (playlist and guide only) or `"web"` (viewer page only) |
| `channel_number` | *(required for TV)* | e.g. `2`, `101`, `2.1`; ignored for `"web"` |
| `name` | `"NEWS"` | in the logo and the TV guide |
| `id` | `"anchorless.news"` | stable id for TV guides (`tvg-id`) |
| `timezone` | `"America/Chicago"` | the on-screen clock, day and night, and the guide |
| `guide_title` | `"Anchorless News"` | the programme title in the TV guide |
| `guide_description` | *(a short description)* | the programme description |
| `guide_slot_minutes` | `30` | guide blocks, starting on the hour; must divide a day; `1440` = one per day |

## `[[extra_channel]]`

Any number of extra channels. Keys: `theme`, `show_on`, `channel_number`, `name`
(required) and `id` (default: from the name), as in `[channel]`.

## `[location]`

Local news. See [Local news](local-news.html).

| Key | Default | |
|---|---|---|
| `city` | none | the local segment's title (`{city}`); without it, `LOCAL` |
| `sources_file` | none | your local feeds file, e.g. `"local.toml"`. No file, no local news. |

## `[rundown]`

See [The newscast](newscast.html).

| Key | Default | |
|---|---|---|
| `refresh_minutes` | `10` | how often feeds are fetched (minimum 1) |
| `page_seconds` | `12` | how long each story is on screen (minimum 3) |
| `intro_seconds` | `5` | the segment title card; `0` = none |
| `transition_seconds` | `0.4` | crossfade between pages, up to 2; `0` = cut |
| `max_story_age_hours` | `12` | older stories are dropped |
| `same_story_similarity` | `0.5` | headline word overlap that makes two items the same story |
| `same_story_text_similarity` | `0.32` | headline + summary similarity that does the same |
| `headline_choice` | `"log"` | `"first"`, `"consensus"` or `"log"` ([details](newscast.html#which-headline-is-shown)) |
| `headline_margin` | `0.15` | how much better (0–1) a version must score to replace the shown one |

### `[[rundown.segment]]`

| Key | Default | |
|---|---|---|
| `name` | *(required)* | the title card; `{city}` becomes your city |
| `stories` | `3` | 1–20 |
| `scope` | any | `"local"`, `"national"` or `"world"` |
| `category` | any | e.g. `"business"` |
| `exclude_scope` | `[]` | leave out stories only these scopes carry |

Listing any segment replaces the default five (TOP STORIES, your city, NATIONAL,
WORLD, BUSINESS).

## `[breaking]`

See [Breaking news](newscast.html#breaking-news).

| Key | Default | |
|---|---|---|
| `enabled` | `true` | |
| `min_sources` | `4` | outlets that must carry a story... |
| `window_minutes` | `30` | ...within this long of its first appearance |
| `cooldown_minutes` | `20` | at most one alert per this long |
| `crawl_tag_minutes` | `60` | how long the red BREAKING tag stays in the crawl |
| `title_prefixes` | `["BREAKING:", "BREAKING NEWS:"]` | a headline starting with one breaks in on its own |
| `local_min_sources` | `5` | outlets needed for a story only local outlets carry |
| `local_alerts` | `"on"` | `"on"`, `"log"` (log only) or `"off"` |
| `sound` | `"auto"` | `"auto"`, `"chiptune"`, `"news"`, `"none"`, or a sound file's path |
| `sound_volume` | `0.8` | 0–2; `1` = as made |

## `[crawl]`

| Key | Default | |
|---|---|---|
| `label` | `"HEADLINES"` | the box at the left of the crawl |
| `speed` | `96` | pixels per second at 480 lines |

## `[audio]`

| Key | Default | |
|---|---|---|
| `music_dir` | `"/music"` | folder of `.mp3` files, shuffled; missing = no music |
| `volume` | `0.5` | 0–2; `1` = as recorded |
| `bitrate` | `"128k"` | audio bitrate |

## `[video]`

See [Performance](performance.html).

| Key | Default | |
|---|---|---|
| `width` / `height` | `854` / `480` | even numbers |
| `fps` | `24` | 1–60 |
| `encoder` | `"x264"` | `"x264"` (CPU) or `"vaapi"` (Intel/AMD GPU) |
| `bitrate` / `maxrate` | `"1500k"` / `"2000k"` | video bitrate |
| `gop_seconds` | `2` | a keyframe this often: how fast a new viewer can start |
| `x264_preset` | `"veryfast"` | x264 speed/quality preset |
| `x264_threads` | `0` | `0` = automatic; fewer threads use less CPU |
| `vaapi_device` | `"/dev/dri/renderD128"` | the GPU's render node |
| `vaapi_rc` | `"vbr"` | `"cqp"` for older Intel GPUs (i965 driver) that reject bitrates |
| `vaapi_qp` | `24` | quality for `"cqp"` (lower = better) |
| `vaapi_convert` | `"cpu"` | `"gpu"` converts colours on the GPU too (less CPU; newer drivers) |

## `[stream]`

| Key | Default | |
|---|---|---|
| `host` | `"0.0.0.0"` | the address to listen on |
| `port` | `9798` | |
| `lead_seconds` | `10` | rendered ahead for a new viewer (Samsung TVs buffer ~10 s) |
| `idle_seconds` | `60` | stop encoding this long after the last viewer leaves |
| `max_sessions` | `2` | channels encoding at once; `-1` = no limit, `0` = nobody can watch |
| `max_viewers` | `-1` | viewers at once, all channels; `-1` = no limit |
| `max_viewers_per_client` | `-1` | viewers from one address; leave at `-1` behind Jellyfin |

## `[web]`

The viewer page. The TV side (playlist, guide, streams) always works over plain http.

| Key | Default | |
|---|---|---|
| `require_https` | `false` | the viewer page only over https |
| `public_status` | `"full"` | `"full"`: `/health` and the viewer page list feeds by name; `"summary"`: counts only |

## `[feeds]`

See [News sources](feeds.html).

| Key | Default | |
|---|---|---|
| `builtin` | `true` | `false` leaves out the built-in outlets |
| `disabled` | `[]` | feed URLs to skip (any feed) |
| `allow_private` | `false` | `true` allows feeds on your own network |

## `[[source]]`

Your own feeds. See [Adding a feed](feeds.html#adding-a-feed).

| Key | Default | |
|---|---|---|
| `name` | *(required)* | the outlet; same name = same outlet |
| `url` | *(required)* | |
| `scope` | `"national"` | `"national"` or `"world"` (`"local"` in the local feeds file) |
| `category` | `"general"` | `"business"` feeds BUSINESS |
| `weight` | `1.0` | ranking weight |
| `enabled` | `true` | |
| `compressed` | `true` | `false` for feeds that always time out |
| `exclude` | `[]` | regular expressions; matching headlines or links are skipped |

## `[admin]`

The settings page. See [Settings page](settings-page.html).

| Key | Default | |
|---|---|---|
| `password` | none | 12+ characters; best from `ANCHORLESS__ADMIN__PASSWORD` |
| `password_hash` | none | from `anchorless hash-password`; set this *or* `password` |
| `allow_from` | private networks | addresses or CIDR ranges that may open the settings page |
| `trusted_proxies` | `[]` | your reverse proxy's address, so `X-Forwarded-For` is believed |
| `session_days` | `30` | how long a login lasts |
| `require_https` | `true` | log in only over https; localhost is always allowed |

## `[data]`

| Key | Default | |
|---|---|---|
| `dir` | `"data"` | where Anchorless keeps its story database and settings history (`/data` in Docker) |

## Settings that moved

An old config with a renamed setting stops with a message naming the new one:

| Old | New |
|---|---|
| `[theme] name` | `[channel] theme` |
| `[theme] crawl_label` / `crawl_speed` | `[crawl] label` / `speed` |
| `[channel] number` | `channel_number` |
| `[channel] in_guide` | `show_on` |
