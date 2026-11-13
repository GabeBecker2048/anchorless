---
title: Performance
---

## What it costs

- **Nobody watching: almost nothing.** Anchorless fetches feeds every 10
  minutes and otherwise sleeps. No frames are drawn and ffmpeg isn't running.
- **Each channel being watched: one encoder.** How much of a core that takes
  depends on your CPU (and on the picture size, frame rate and encoder). Ten
  people watching the *same* channel cost the same as one.
- **Memory:** the example compose file caps it at 512 MB.

A channel starts when its first viewer tunes in (about 2 seconds) and stops 60
seconds after the last one leaves (`[stream] idle_seconds`).

## Viewer limits

```toml
[stream]
max_sessions = 2              # channels encoding at once; -1 = no limit
max_viewers = -1              # viewers at once, all channels together
max_viewers_per_client = -1   # viewers from one address
```

- `max_sessions` is the CPU cap: with the default `2`, a third channel can't
  start while two others are on. Viewers joining a channel that's already on
  don't count.
- `max_viewers` counts everyone: TV apps, browsers and phones.
- `max_viewers_per_client` stops one address taking every slot. **Leave it at
  `-1` if you use Jellyfin** (or another TV server): all its viewers come from its
  one address. A household behind one router is one address too.

A viewer over a limit sees **BUSY** on the viewer page, and TV apps get an HTTP
503 ("try again later").

## Lighter on the CPU

In rough order of how much they help:

1. **Hardware encoding** (below) moves most of the work to the GPU.
2. **Fewer threads:** `[video] x264_threads = 2` uses less CPU in total, at the
   cost of a slightly slower start.
3. **A lower frame rate:** `[video] fps = 15` encodes fewer frames; the pages are mostly still text.
4. **Keep the default size.** 1280×720 has more than twice the pixels of 854×480, and costs accordingly.

## Hardware encoding

Intel and AMD GPUs can encode with VA-API. The container image includes the
drivers (Intel's only on amd64).

**Docker:** pass the GPU through and add the host's `render` group:

```yaml
    devices: ["/dev/dri:/dev/dri"]
    group_add: ["992"]   # your host's render group id: getent group render
```

**Then, in `config.toml`:**

```toml
[video]
encoder = "vaapi"
```

Restart, start watching, and check the log for errors. If it fails:

| Problem | Try |
|---|---|
| Older Intel GPU (i965 driver) rejects the bitrate | `vaapi_rc = "cqp"` (constant quality; `vaapi_qp = 24`, lower = better) |
| Wrong GPU, or more than one | `vaapi_device = "/dev/dri/renderD129"` |
| Permission denied on `/dev/dri` | the `group_add` id doesn't match `getent group render` on the host |

On newer Intel drivers, `vaapi_convert = "gpu"` also converts colours on the GPU,
saving most of what's left of ffmpeg's CPU use.

Natively, install your distribution's VA-API driver (`intel-media-va-driver` or
`mesa-va-drivers`); `vainfo` shows whether it works.

## Start-up delay on TVs

New viewers get 10 seconds rendered ahead at once (`[stream] lead_seconds`), so
TVs that buffer before playing (Samsung, and Jellyfin's clients) start quickly.
Lowering it saves a little work per tune-in but means a longer black screen on
those TVs. `[video] gop_seconds` (default 2) is how often a new viewer can join
the stream; lower means faster joins and a slightly bigger stream.
