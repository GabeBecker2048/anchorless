# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Anchorless: a 24/7 text newscast for IPTV. Public RSS headlines in, an MPEG-TS stream (plus M3U playlist and XMLTV guide) out, for Jellyfin, Plex, Channels DVR or any IPTV player. No browser: Pillow draws every frame, ffmpeg encodes. Python 3.12+, packaged with hatchling, run with uv. Shipped mainly as a container image (it needs ffmpeg).

## Commands

```bash
uv sync                              # create/refresh .venv from uv.lock
cp config.example.toml config.toml   # config.toml is gitignored
uv run anchorless serve              # the station on :9798 (viewer at /, settings at /settings)
uv run anchorless check-config       # validate the config (never prints secrets)
uv run anchorless headlines          # every multi-outlet story's versions, scored
uv run pytest                        # tests
uv run ruff check .                  # lint (CI runs both)
```

Visual changes (anything in `render/`) can't be judged from tests: render frames and look at them.

## Architecture

- `sources/rss.py` fetches feeds (httpx, through the SSRF guard in `netguard.py`) -> `Story`s (`models.py`).
- `pipeline.py` groups the same story across outlets into `Cluster`s (headline word overlap, then TF-IDF) and builds the rundown; `cluster.stories[0]` is the lead, i.e. the headline shown.
- `headline.py` is the "consensus headline": which outlet's wording to show. It must stay **outlet-blind** (no outlet is named or rated anywhere) and conservative: it only replaces a headline with a red flag. `[rundown] headline_choice = "log"` runs it in shadow mode.
- `breaking.py` decides breaking news; `newsroom.py` refreshes on a timer and holds the current state.
- `render/`: `studio.py` (the pixel-art set, an isometric 2:1 projection: centre things in 3D, a box top's visual centre is half its depth back from the front face), `pages.py` (Classic), `crawl.py`, `theme.py`.
- `stream/`: `server.py` (`Station` and `Channel`s: ffmpeg starts on the first viewer and stops after the last; viewer limits), `encoder.py`, `playout.py`, `tsbuffer.py` (HLS cut from memory), `web.py` (viewer, status, settings API, security headers/CSP), `admin.py` (settings login).
- `config.py`: pydantic models; env overrides `ANCHORLESS__SECTION__KEY`. `settings.py`: the settings page edits the TOML file in place with tomlkit. **The file is the source of truth**: per-field conflict checks, validate before writing, atomic replace, a change history.

## Rules

- **No personal or local details in the repo.** Locations and local outlet names live only in a user's `.env` / local feeds file. Test fixtures, examples, screenshots and the README GIF use made-up outlets and headlines.
- Security behaviour is documented in SECURITY.md and the guide's "Hosting publicly" checklist: keep them true when changing `netguard.py`, `admin.py`, `web.py` or the `[stream]` limits.
- No inline script or style in the web pages (the CSP forbids it).

## Releasing

1. Bump `version` in `pyproject.toml` (the only place it lives; `anchorless.__version__` reads it), run `uv lock`.
2. Add `## X.Y.Z — YYYY-MM-DD` at the top of `CHANGELOG.md`: one paragraph, what changed for users.
3. Commit and push to main, then `scripts/release.sh`: it checks everything and pushes the tag `vX.Y.Z`.
4. `.github/workflows/release.yml` builds and pushes `ghcr.io/gabebecker2048/anchorless` (`X.Y.Z`, `X.Y`, `latest`; amd64 + arm64) and creates the GitHub release from the CHANGELOG entry.
