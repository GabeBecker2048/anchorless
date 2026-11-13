---
title: Local news
---

Out of the box Anchorless shows national and world news. Add your area's
outlets and it gets a **local segment** (titled with your city) and **local
breaking news**. It takes three things: your city's name, a few local feeds, and
a file to keep them in.

> Local news puts your city on screen, and the feeds name your area's outlets.
> Anchorless keeps both out of `config.toml` on purpose, so you can share that
> file without saying where you live.
{: .tip }

## 1. Set your city

The city is the local segment's title. Set it in the environment rather than the
config file:

```yaml
# docker-compose.yml
    environment:
      ANCHORLESS__LOCATION__CITY: Springfield
```

```sh
# native
export ANCHORLESS__LOCATION__CITY=Springfield
```

(It works in `config.toml` too, as `[location] city = "Springfield"`.) Without a
city, the segment is titled `LOCAL`.

## 2. Find your outlets' feeds

You want an RSS or Atom feed from each local newspaper, TV station, radio
newsroom or news site. Three to six outlets is plenty. Ways to find them:

- **Look for an RSS link.** Often in the site footer, or on a page called
  "RSS", "Feeds" or "Newsletters & alerts".
- **Search the page source.** Open the home page or the local-news section,
  view the source (<kbd>Ctrl</kbd>+<kbd>U</kbd>), and search for `rss` or
  `application/rss+xml`. The `href` next to it is the feed.
- **Try the usual addresses.** Many news sites run on the same few systems:

  | Site built on | Try |
  |---|---|
  | WordPress (many TV stations and small outlets) | `https://example.com/feed/`, or a section: `https://example.com/news/local/feed/` |
  | Arc XP (many TV stations and newspapers) | `https://example.com/arc/outboundfeeds/rss/?outputType=xml`, or a section: `.../arc/outboundfeeds/rss/category/news/local/?outputType=xml` |
  | BLOX / TownNews (many newspapers) | `https://example.com/search/?f=rss&t=article&c=news/local&l=50` |

  A feed opens in the browser as XML (or downloads). A normal web page means
  that address isn't a feed.

**Use the local section's feed** wherever an outlet has one. A station's main
feed is usually full of national and wire stories, and every story from a local
feed counts as local.

## 3. List them in a local feeds file

Create `local.toml` next to `config.toml` (in Docker: in the `config/` folder).
`anchorless init` writes `local.example.toml` as a starting point.

```toml
# local.toml - your local outlets. Every source here counts as local.

[[source]]
name = "Springfield Daily"
url = "https://www.example.com/news/local/rss.xml"

[[source]]
name = "Channel 7 Eyewitness News"
url = "https://www.example.com/feeds/local"
exclude = ["/sports/", "sponsored"]   # skip sports and ads

[[source]]
name = "Channel 7 Eyewitness News"         # same name = the same outlet
url = "https://www.example.com/feeds/weather"
```

Then point the config at it, again from the environment or in the file:

```yaml
      ANCHORLESS__LOCATION__SOURCES_FILE: local.toml
```

```toml
# or in config.toml
[location]
sources_file = "local.toml"   # relative to config.toml
```

Each `[[source]]` takes the same fields as any feed (see [News sources](feeds.html#adding-a-feed)),
except `scope`: everything in this file is local.

### Or use the settings page

If the [settings page](settings-page.html) is on, open **Feeds**, add a feed
under **Local**, and press **Check feed** to test it. Your first local feed
creates `local.toml` and sets `sources_file` for you. Local feeds are always
written to that file, never to `config.toml`.

## 4. Check it

```sh
anchorless fetch
# Docker: docker compose exec anchorless anchorless fetch
```

This prints the rundown with a `== SPRINGFIELD` segment, and lists any feed that
failed with its error. The viewer page's **Feeds** card shows the same. Changes
to `local.toml` are picked up on the next fetch, no restart needed.

## Tuning

**National stories in the local segment?** Switch to the outlet's local-section
feed, or skip unwanted items with `exclude` (regular expressions, case-insensitive, matched
against the headline and the link):

```toml
exclude = ["/nation-world/", "/sports/", "^watch:", "lottery"]
```

**A feed always times out?** Some servers never answer a request that accepts
compressed responses. Add `compressed = false` to that source.

**Too few local stories?** Raise `[rundown] max_story_age_hours` (default 12),
or the segment's `stories` count (see [The newscast](newscast.html#segments)).

**Local breaking news.** A story only local outlets carry breaks in when
`local_min_sources` outlets (default 5) report it within the window, since local
newsrooms tend to cover the same events. A headline starting with `BREAKING:`
still breaks in on its own.

```toml
[breaking]
local_min_sources = 3   # fewer outlets in your area? lower this
local_alerts = "log"    # "on", "log" (only log what would have broken in), or "off"
```

**A feed on your own network** (a self-hosted aggregator, say) is blocked by
default. See [`allow_private`](feeds.html#feeds-on-your-own-network).

## Keeping it private

- Keep `local.toml` and your `.env` out of anything you publish or share.
- If you [host the channel publicly](hosting-publicly.html), remember the city
  shows on screen and the viewer page lists feeds by name
  (`[web] public_status = "summary"` hides the list).
