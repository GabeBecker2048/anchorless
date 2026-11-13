---
title: News sources
---

Anchorless reads public RSS and Atom feeds. It comes with a list of national
and world outlets; you can add your own, turn any off, or replace the list
entirely. Local outlets have their own page: [Local news](local-news.html).

## Built-in outlets

| Outlet | Feeds |
|---|---|
| NPR | news, US, politics (national) · world · business |
| The New York Times | home page, US (national) · world · business |
| CBS News | US (national) · world · MoneyWatch (business) |
| ABC News | top stories (national) |
| NBC News | news (national) |
| Fox News | latest (national) |
| The Guardian | US news (national) · world |
| BBC News | US & Canada (national) · world |
| Al Jazeera | all (world) |
| PBS NewsHour | headlines, politics (national) · world |
| CNBC | two business feeds |

`anchorless check-config` prints every feed URL in use.

## Adding a feed

Add a `[[source]]` to `config.toml` for each feed:

```toml
[[source]]
name = "Example Wire"
url = "https://example.com/world/rss.xml"
scope = "world"
category = "general"
```

| Field | Default | What it does |
|---|---|---|
| `name` | *(required)* | The outlet's name, shown on screen. Feeds with the same name count as **one outlet** (for breaking news and for grouping). |
| `url` | *(required)* | The feed's address. |
| `scope` | `"national"` | `"national"` or `"world"`: which segment its stories go to. (Local feeds go in the [local feeds file](local-news.html).) |
| `category` | `"general"` | `"business"` feeds the BUSINESS segment. Any other word works too, for a [segment of your own](newscast.html#segments). |
| `weight` | `1.0` | How much this outlet's stories count when ranking; higher also prefers its version of a shared story. `0` keeps its stories at the bottom. |
| `enabled` | `true` | `false` keeps the entry but stops fetching it. |
| `compressed` | `true` | `false` if the feed always times out (some servers hang on compressed requests). |
| `exclude` | `[]` | Regular expressions (case-insensitive). Items whose headline or link match are skipped, e.g. `["/sports/", "^watch:"]`. |

The [settings page](settings-page.html) can add, edit, test ("Check feed") and
switch feeds too.

## Turning feeds off

Turn off any feed (built-in, your own or local) by its URL:

```toml
[feeds]
disabled = ["https://moxie.foxnews.com/google-publisher/latest.xml"]
```

To use **only your own** feeds, leave out the built-in list:

```toml
[feeds]
builtin = false
```

At least one feed must be on, or Anchorless won't start.

## Feeds on your own network

Feed requests (and any redirects) must go to a public internet address, so that
a URL typed into the settings page can't point the server at your router or
other services on your network. For a feed served on your own network:

```toml
[feeds]
allow_private = true
```

This is file-only and needs a restart.

## How often feeds are fetched

Every 10 minutes (`[rundown] refresh_minutes`). Anchorless uses conditional
requests, spaces out feeds from the same site, and keeps showing a feed's last
stories if it fails for a while. Stories older than `max_story_age_hours`
(default 12) drop out.

Test your feeds any time with `anchorless fetch`: it prints the rundown and
every failed feed with its error.

## What a good feed looks like

- **It has headlines and publish dates.** Undated items still work but rank lower.
- **It's news, not everything.** Prefer a section feed (`/news/`, `/world/`) to
  an all-content feed full of videos, podcasts and promotions.
- **Items like "Watch live" or "Morning briefing"** are skipped automatically.

## Sources and fair use

Anchorless shows only what feeds publish for display: headlines, short
summaries and the outlet's name. It never shows article text. Each outlet's feed
terms apply to how you use its feed; many allow personal, non-commercial use
only. Headlines belong to their outlets.
