---
title: The newscast
---

Every 10 minutes Anchorless fetches its feeds, groups the same story from
different outlets together, ranks the stories (newer, and carried by more
outlets, ranks higher) and builds a **rundown**: segments that play in order,
then loop.

## Segments

The default rundown:

```toml
[[rundown.segment]]
name = "TOP STORIES"
stories = 4
exclude_scope = ["local"]   # stories only local outlets carry stay in the local segment

[[rundown.segment]]
name = "{city}"             # the local segment, titled with your city
stories = 3
scope = "local"

[[rundown.segment]]
name = "NATIONAL"
stories = 3
scope = "national"

[[rundown.segment]]
name = "WORLD"
stories = 3
scope = "world"

[[rundown.segment]]
name = "BUSINESS"
stories = 2
category = "business"
```

| Field | What it does |
|---|---|
| `name` | The segment's title card. `{city}` becomes your [city](local-news.html) (or `LOCAL`). |
| `stories` | How many stories, 1–20. |
| `scope` | Only stories from `"local"`, `"national"` or `"world"` feeds. Leave out for any. |
| `category` | Only stories from feeds with this [category](feeds.html#adding-a-feed), e.g. `"business"`. Leave out for any. |
| `exclude_scope` | Leave out stories that *only* feeds of these scopes carry. |

- A story appears in the **first** segment it fits, and nowhere else.
- A segment with no stories to show is skipped.
- Writing any `[[rundown.segment]]` replaces the whole default list, so list
  every segment you want.

For example, a technology segment fed by feeds with `category = "tech"`:

```toml
[[rundown.segment]]
name = "TECH"
stories = 2
category = "tech"
```

The [settings page](settings-page.html) can add, remove, rename and reorder segments.

## Timing

```toml
[rundown]
page_seconds = 12          # each story on screen
intro_seconds = 5          # the segment's title card (0 = none)
transition_seconds = 0.4   # crossfade between pages (0 = cut)
refresh_minutes = 10       # how often the feeds are fetched
max_story_age_hours = 12   # older stories are dropped
```

With the defaults, one pass through a full rundown takes about three and a half minutes.

### Grouping the same story

Two headlines are treated as the same story when enough of their words overlap
(`same_story_similarity`, default 0.5), or their headline and summary text are
similar enough (`same_story_text_similarity`, default 0.32). Lower values group
more aggressively; raise them if different stories get merged.

## Breaking news

A story breaks in, interrupting the rundown with an alert and a sound, when it
first appeared within the last 30 minutes and either:

- **4 or more outlets** already carry it, or
- an outlet's headline starts with `BREAKING:` or `BREAKING NEWS:`.

```toml
[breaking]
enabled = true
min_sources = 4             # outlets that must carry a story...
window_minutes = 30         # ...within this long of its first appearance
cooldown_minutes = 20       # at most one alert per this long
crawl_tag_minutes = 60      # how long it keeps the red BREAKING tag in the crawl
title_prefixes = ["BREAKING:", "BREAKING NEWS:"]
local_min_sources = 5       # for stories only local outlets carry
local_alerts = "on"         # "on", "log" (only log what would break in) or "off"
sound = "auto"
sound_volume = 0.8
```

A story never breaks in twice. Outlets with the same name (several feeds from
one outlet) count once.

### Alert sounds

| `sound` | Plays |
|---|---|
| `"auto"` | chiptune on Studio channels, a synth-brass news sting on Classic ones |
| `"chiptune"` / `"news"` | that one on every channel |
| `"none"` | nothing |
| a file path | your own sound, in any format ffmpeg reads |

The music ducks under the alert either way. A file path can only be set in
`config.toml`, not on the settings page.

## Which headline is shown

When several outlets carry a story, one headline is shown.

| `[rundown] headline_choice` | Shows |
|---|---|
| `"first"` | The first-published version (preferring one with a summary). |
| `"consensus"` | Usually the same, but replaces it when it has a red flag (see below) and another version is clean, at least as complete, and clearly better. |
| `"log"` *(default)* | Shows `"first"`, and lists what `"consensus"` would change on the settings page and in the log, so you can judge it before switching it on. |

Red flags: an editorializing word no other outlet uses ("slams", "meltdown"...),
shouting in capitals, an exclamation mark, or wording almost none of the other
outlets share. Words and "!" inside quotation marks are someone's quote, so they
don't count. No outlet is named or rated anywhere: the choice comes only from
what the outlets wrote. `headline_margin` (default 0.15) is how much better a
version must score to replace the first one.

`anchorless headlines` prints every version of every shared story with its
score and the reason for each choice.

## Music

Anchorless includes no music. Give it a folder of MP3s you have the right to
play and it shuffles them underneath the news:

```toml
[audio]
music_dir = "/music"   # default; a missing folder means just the sound effects
volume = 0.5           # 1 = as recorded
```

In Docker, mount your folder at `/music` (read-only is fine):

```yaml
    volumes:
      - /path/to/music:/music:ro
```

Only `.mp3` files are played. New files are picked up when a channel next starts.
