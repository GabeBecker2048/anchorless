# Security

## Reporting a vulnerability

Please report security problems **privately**, not in a public issue:
use GitHub's **"Report a vulnerability"** button on this repository's
**Security** tab. Only the maintainer can see the report.

Please include what you found, how to reproduce it, and which version (or
commit) you used. Anchorless is a hobby project, so there is no guaranteed
response time, but reports are taken seriously: you'll get an answer, a fix
where one is needed, and credit in the advisory if you'd like it.

## Supported versions

Only the latest release (and `main`) gets security fixes.

| Version | Supported |
|---|---|
| 1.x | yes |

## What counts

**In scope** - for example:

- getting into the settings page, or changing settings, without the password
- getting past `[admin] allow_from`, `trusted_proxies` or `require_https`
- making the server fetch a private-network address despite
  `[feeds] allow_private = false`
- reading files or secrets: the password, the config, the local feeds file
- script injection in the viewer or settings page (headlines are untrusted)
- a stream or request that crashes the server or exhausts its memory despite the
  `[stream]` limits

**Not a vulnerability** - by design (see [Hosting publicly](https://gabebecker2048.github.io/anchorless/hosting-publicly.html) in the docs):

- anyone who can reach the TV side (`/playlist.m3u`, `/guide.xml`, `/live.ts`,
  `/hls/`) or the viewer page can watch, and watching costs CPU - that is what
  `max_sessions`, `max_viewers` and `max_viewers_per_client` are for
- problems that need the settings password, or access to the server or its
  config files
- weaker setups chosen on purpose, such as `require_https = false` or a wide
  `allow_from`

## Security advisories

None yet.
