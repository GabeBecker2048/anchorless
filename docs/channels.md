---
title: Looks and channels
---

## Themes

| `theme` | Look |
|---|---|
| `studio` | The empty pixel-art news set: headlines on the big screen behind the desk, a window on the city that follows the time of day. |
| `classic-light` | Full-screen cable-news pages in blue. |
| `classic-dark` | The same pages in charcoal and near-black. |
| `classic` | Light by day (6:00–19:00 local time), dark at night. |

```toml
[channel]
theme = "studio"
```

The viewer and settings pages take on the look of the channel you watch (the
settings page: the main channel's).

To see every page type in a look without starting the stream:

```sh
anchorless render -t classic-dark -o out      # PNG stills in ./out
anchorless preview -t studio --breaking       # a 60 s MP4 in out/preview.mp4
```

## The main channel

```toml
[channel]
theme = "studio"       # required
show_on = "both"       # required: "both", "tv" or "web"
channel_number = 101   # required for "both" and "tv"
name = "NEWS"          # in the logo and the TV guide
```

| `show_on` | Listed in the TV playlist and guide | Listed on the viewer page |
|---|---|---|
| `"both"` | yes | yes |
| `"tv"` | yes | no |
| `"web"` | no | yes |

`show_on` only decides where a channel is *listed*: its stream URL still plays
for anyone who opens it. `channel_number` can be a whole number or a subchannel
like `2.1`; it is ignored for `"web"`.

The main channel's stream is `/live.ts`.

## More channels

Add as many `[[extra_channel]]`s as you like, for example a Studio channel for
the TV and a Classic one for the browser. They all show the same news (one
fetch feeds them all), and each one is only drawn and encoded while someone is
watching it.

```toml
[[extra_channel]]
theme = "classic"
name = "NEWS CLASSIC"   # required for extra channels
show_on = "web"

[[extra_channel]]
theme = "studio"
name = "NEWS 2"
show_on = "tv"
channel_number = 102    # must differ from every other TV channel
```

An extra channel's stream is `/live/<id>.ts`, where the id comes from its name
(`NEWS 2` → `anchorless.news-2`). Set `id` yourself to keep the stream URL and
the TV guide's channel id the same if you rename it later:

```toml
id = "anchorless.news-2"
```

> Each channel being watched costs about 30% of a CPU core, and by default only
> two can be on at once (`[stream] max_sessions = 2`). See [Performance](performance.html).
{: .tip }

## Clock and TV guide

These live in `[channel]` and apply to every channel:

```toml
[channel]
timezone = "America/Chicago"   # the on-screen clock, day/night, and the guide
guide_title = "Anchorless News"
guide_description = "Around-the-clock headlines from national and world news outlets."
guide_slot_minutes = 30        # guide blocks start on :00 and :30; 1440 = one per day
```

`timezone` takes any [tz database name](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)
(`Europe/London`, `Australia/Sydney`, ...). `guide_slot_minutes` must divide a
day evenly (15, 30, 60, ...).

## The crawl

The headline ticker along the bottom, on every channel:

```toml
[crawl]
label = "HEADLINES"   # the box at the left
speed = 96            # pixels per second at 480 lines (scaled for bigger pictures)
```

## Picture size

The default is 854×480 at 24 fps, sharp enough for text and cheap to encode.
For a bigger picture:

```toml
[video]
width = 1280
height = 720
bitrate = "2500k"
maxrate = "3500k"
```

Width and height must be even. Bigger pictures cost more CPU; see
[Performance](performance.html).
