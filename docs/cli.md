---
title: Command line
---

```
anchorless [-c CONFIG] [-v] <command> [options]
```

| Option | |
|---|---|
| `-c`, `--config` | the config file (default: `$ANCHORLESS_CONFIG`, or `./config.toml`) |
| `-v`, `--verbose` | more detail in the log |
| `--version` | print the version |

In Docker, run commands inside the container:

```sh
docker compose exec anchorless anchorless fetch
```

## `init`

```sh
anchorless init [FOLDER] [--force]
```

Writes a starter `config.toml` (every setting explained) and `local.example.toml`
into `FOLDER` (default: here). `--force` replaces an existing `config.toml`.

## `serve`

```sh
anchorless serve [--init]
```

Runs the station on port 9798: the viewer page, the TV playlist and guide, the
streams and the settings page. `--init` first writes a starter config if there
is none (the container does this on its first start).

## `fetch`

```sh
anchorless fetch [--json]
```

Fetches every feed once and prints the rundown: each segment's stories, their
age and outlets, then any feed that failed and why. The quickest way to test a
config or a new feed. `--json` prints it as JSON.

## `check-config`

```sh
anchorless check-config
```

Validates the config (including the local feeds file and environment variables)
and prints every setting as Anchorless sees it. The password and its hash show
as `<set>`.

## `render`

```sh
anchorless render [-t THEME] [-o OUT]
```

Writes PNG stills of every page type (segment intro, story, breaking alert, ...)
with the current news to `OUT` (default `out`). `-t` picks a theme: `studio`,
`classic`, `classic-light` or `classic-dark` (default: the configured one).

## `preview`

```sh
anchorless preview [-t THEME] [-o OUT] [-s SECONDS] [--breaking]
```

Writes a short MP4 of the channel, with music and sound, to `OUT` (default
`out/preview.mp4`). `-s` sets the length (default 60 seconds); `--breaking`
starts with a sample breaking-news alert.

## `headlines`

```sh
anchorless headlines [--dump FILE]
```

Prints every story more than one outlet carries, with each outlet's version, its
score, and whether the [consensus headline](newscast.html#which-headline-is-shown)
would change what is shown and why. `--dump` appends the stories (never local
ones) to a JSON-lines file.

## `hash-password`

```sh
anchorless hash-password [--stdin]
```

Asks for a settings password twice (12+ characters) and prints a
`password_hash` line for `[admin]` in `config.toml`. `--stdin` reads the password
from standard input instead, for scripts. Needs no config file.
