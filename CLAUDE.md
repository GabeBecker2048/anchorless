# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Anchorless: a 24/7 text newscast for IPTV. Public RSS headlines in, an MPEG-TS stream (plus M3U playlist and XMLTV guide) out, for Jellyfin, Plex, Channels DVR or any IPTV player. No browser: Pillow draws every frame, ffmpeg encodes. Python 3.12+, packaged with hatchling, run with uv. Shipped on PyPI (`pip install anchorless`, then `anchorless init`, needs ffmpeg) and as a container image.

## Commands

```bash
uv sync                              # create/refresh .venv from uv.lock
uv run anchorless init               # writes config.toml (gitignored) from config.example.toml
uv run anchorless serve              # the station on :9798 (viewer at /, settings at /settings)
uv run anchorless check-config       # validate the config (never prints secrets)
uv run anchorless headlines          # every multi-outlet story's versions, scored
uv run pytest                        # tests
uv run ruff check .                  # lint (CI runs both)
uv run python scripts/record_gif.py  # re-record the README GIF (docs/studio.gif) after a Studio change
```

Visual changes (anything in `render/`) can't be judged from tests: render frames and look at them (`uv run anchorless -c config.example.toml render -t studio -o out`). If the Studio look changed, re-record the README GIF with `scripts/record_gif.py`.

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
- Security behaviour is documented in SECURITY.md and the docs' checklist (`docs/hosting-publicly.md`): keep them true when changing `netguard.py`, `admin.py`, `web.py` or the `[stream]` limits.
- `docs/` is the user docs site (Jekyll, built by GitHub Pages from `/docs` on `main`, styled like the Studio web UI; layout in `docs/_layouts/`, nav in `docs/_data/nav.yml`). It is the source of truth for users: how to use Anchorless, never how the code works. Update it in the same PR when a setting, command, default or user-visible behaviour changes. CI's `docs` job builds it with Pages' own builder, checks every internal link (`scripts/check_docs.py`) and uploads the built site as the `docs-site` artifact.
- No inline script or style in the web pages (the CSP forbids it).

## Changes and releases

`main` only changes through pull requests that pass CI (`all-green`); nobody pushes to it directly. Work on a branch, `gh pr create`, wait for CI, `gh pr merge --squash`.

Releasing:
1. On a branch: bump `version` in `pyproject.toml` (the only place it lives; `anchorless.__version__` reads it), run `uv lock`, and add `## X.Y.Z — YYYY-MM-DD` at the top of `CHANGELOG.md` with one sentence (two at most) on what changed for users. The changelog is minimal on purpose.
2. Merge that PR, update local `main`, then `scripts/release.sh X.Y.Z` (`--dry-run` to rehearse): it checks the version against `pyproject.toml`, the CHANGELOG section, that you are on `main` level with `origin/main` with a clean tree, that the tag is unused and `uv.lock` is current, then pushes the tag `vX.Y.Z`. It runs no tests; CI did that on the PR, and the release workflow does it again. The script is identical in anchorless, chesssnake and whirligig.
3. `.github/workflows/release.yml` tests again, then publishes to PyPI (trusted publishing, the `pypi` environment), pushes `ghcr.io/gabebecker2048/anchorless` (`X.Y.Z`, `X.Y`, `X`, `latest`; amd64 + arm64), and creates the GitHub release from the CHANGELOG entry with the wheel and sdist attached.

`config.example.toml` and `local.example.toml` are what `anchorless init` writes: the wheel carries them (pyproject force-include), and `examples.py` falls back to the repo root in a checkout. The README and `docs/install.md` embed `deploy/docker-compose.example.yml` verbatim (a test checks it).
