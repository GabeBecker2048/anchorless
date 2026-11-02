"use strict";
const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const ICON = {
  vol: '<path d="M4 9v6h4l5 4V5L8 9H4zm12.5 3a4.5 4.5 0 0 0-2.5-4v8a4.5 4.5 0 0 0 2.5-4zM14 3.2v2.1a7 7 0 0 1 0 13.4v2.1a9 9 0 0 0 0-17.6z"/>',
  muted: '<path d="M4 9v6h4l5 4V5L8 9H4zm12.6 3 2.7-2.7-1.4-1.4-2.7 2.7-2.7-2.7-1.4 1.4 2.7 2.7-2.7 2.7 1.4 1.4 2.7-2.7 2.7 2.7 1.4-1.4z"/>',
  fs: '<path d="M4 4h6v2H6v4H4V4zm10 0h6v6h-2V6h-4V4zM4 14h2v4h4v2H4v-6zm14 0h2v6h-6v-2h4v-4z"/>',
  unfs: '<path d="M8 4h2v6H4V8h4V4zm6 0h2v4h4v2h-6V4zM4 14h6v6H8v-4H4v-2zm10 0h6v2h-4v4h-2v-6z"/>',
};

let status = null;          // the latest /api/status
let channelId = null;
let player = null;          // the mpegts.js player while watching
const video = $("video"), box = $("player");

// ---------- time ----------
function ago(iso) {
  if (!iso) return "";
  const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000);
  if (s < 90) return "just now";
  if (s < 3600) return Math.round(s / 60) + " min ago";
  if (s < 86400 * 2) return Math.round(s / 3600) + " h ago";
  return Math.round(s / 86400) + " days ago";
}
function clock(iso) {
  if (!iso) return "-";
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", timeZone: status?.timezone });
}

// ---------- the player ----------
// "2 NEWS", or just the name for a web-only channel (it has no channel number).
function label(c) { return c.number ? `${c.number} ${c.name}` : c.name; }
function channel() { return status?.channels.find((c) => c.id === channelId) || status?.channels[0]; }

function setPoster() {
  const ch = channel();
  if (ch && !player) $("poster").src = `/poster/${encodeURIComponent(ch.id)}.png?t=${Date.now()}`;
}

// Two ways to play: mpegts.js reads the raw MPEG-TS stream (most browsers), and
// the browser's own HLS player (iPhone Safari, which has no MediaSource) reads
// the same stream cut into 2-second pieces. ?engine=hls forces the second.
const forceHls = new URLSearchParams(location.search).get("engine") === "hls";
function engine() {
  if (!forceHls && window.mpegts && mpegts.getFeatureList().mseLivePlayback) return "mpegts";
  if (video.canPlayType("application/vnd.apple.mpegurl")) return "hls";
  return null;
}

function failed(text) {
  stop();
  box.classList.add("error");
  $("msg").textContent = text;
}

// Why this channel can't be watched right now ([stream] max_sessions / max_viewers), if so.
function busy(ch) {
  const l = status?.limits;
  if (!l) return null;
  if (l.max_viewers >= 0 && l.viewers >= l.max_viewers) {
    return l.max_viewers === 0 ? "NOBODY CAN WATCH RIGHT NOW (max_viewers = 0)" : `BUSY: ${l.viewers} ALREADY WATCHING, THE MOST ALLOWED`;
  }
  if (!ch.running && l.max_sessions >= 0 && l.sessions >= l.max_sessions) {
    if (l.max_sessions === 0) return "NO CHANNEL CAN START RIGHT NOW (max_sessions = 0)";
    const on = status.channels.filter((c) => c.running).map((c) => c.name).join(", ");
    return `BUSY: ${l.sessions} CHANNEL${l.sessions > 1 ? "S" : ""} ALREADY ON${on ? " (" + on + ")" : ""} - TRY ONE OF THOSE, OR AGAIN LATER`;
  }
  return null;
}

function watch() {
  const ch = channel();
  if (!ch || player) return;
  const full = busy(ch);
  if (full) { box.classList.add("error"); $("msg").textContent = full; return; }
  const how = engine();
  if (!how) {
    box.classList.add("error");
    $("msg").textContent = "THIS BROWSER CAN'T PLAY THE STREAM - USE /playlist.m3u IN VLC";
    return;
  }
  box.classList.remove("error");
  box.classList.add("playing", "loading");
  $("msg").textContent = "TUNING IN…";
  if (how === "hls") {
    player = { hls: true };
    video.src = ch.hls;
    video.play().catch(() => {});
    poke();
    return;
  }
  player = mpegts.createPlayer({ type: "mpegts", isLive: true, url: ch.stream },
    { enableStashBuffer: true, liveBufferLatencyChasing: false, lazyLoad: false, autoCleanupSourceBuffer: true });
  player.attachMediaElement(video);
  player.on(mpegts.Events.ERROR, (type, detail, info) => failed(info && info.code === 503
    ? "BUSY - THE CHANNEL LIMIT IS REACHED. TRY AGAIN SHORTLY"
    : "LOST THE SIGNAL (" + (detail || type) + ") - PRESS PLAY TO RETRY"));
  player.load();
  const p = player.play();
  if (p && p.catch) p.catch(() => { /* playback starts once data arrives */ });
  poke();
}

function stop() {
  if (!player) return;
  const p = player; player = null;
  if (p.hls) { video.pause(); video.removeAttribute("src"); video.load(); }
  else { try { p.pause(); p.unload(); p.detachMediaElement(); p.destroy(); } catch (e) { /* already gone */ } }
  box.classList.remove("playing", "loading", "idle");
  if (document.fullscreenElement) document.exitFullscreen();
  setPoster();
}

video.addEventListener("playing", () => box.classList.remove("loading"));
video.addEventListener("waiting", () => { if (player) box.classList.add("loading"); });
video.addEventListener("error", () => { if (player && player.hls) failed("LOST THE SIGNAL - PRESS PLAY TO RETRY"); });

function toggleFullscreen() {
  if (document.fullscreenElement) { document.exitFullscreen(); return; }
  if (box.requestFullscreen) box.requestFullscreen().catch(() => {});
  else if (video.webkitEnterFullscreen) video.webkitEnterFullscreen();     // iPhone
}
document.addEventListener("fullscreenchange", () => {
  $("fsicon").innerHTML = document.fullscreenElement ? ICON.unfs : ICON.fs;
  poke();
});

function setMuted(m) { video.muted = m; $("muteicon").innerHTML = m || video.volume === 0 ? ICON.muted : ICON.vol; }
function setVolume(v) { video.volume = Math.min(1, Math.max(0, v)); $("vol").value = video.volume; setMuted(video.volume === 0 ? true : false); }

// Controls and cursor hide after a few still seconds while watching.
let idleTimer = null;
function poke() {
  box.classList.remove("idle");
  clearTimeout(idleTimer);
  if (player) idleTimer = setTimeout(() => { if (player) box.classList.add("idle"); }, 2500);
}

$("bigplay").addEventListener("click", watch);
$("stop").addEventListener("click", stop);
$("mute").addEventListener("click", () => setMuted(!video.muted));
$("vol").addEventListener("input", (e) => setVolume(parseFloat(e.target.value)));
$("fs").addEventListener("click", toggleFullscreen);
box.addEventListener("dblclick", (e) => { if (!e.target.closest(".controls")) toggleFullscreen(); });
box.addEventListener("mousemove", poke);
box.addEventListener("click", (e) => { if (player && !e.target.closest(".controls")) poke(); });
document.addEventListener("keydown", (e) => {
  if (e.target.closest("input, select, textarea") && e.key !== "Escape") return;
  const k = e.key.toLowerCase();
  if (k === "f") { toggleFullscreen(); }
  else if (k === " " || k === "k") { player ? stop() : watch(); }
  else if (k === "m") { setMuted(!video.muted); }
  else if (k === "arrowup") { setVolume(video.volume + 0.1); }
  else if (k === "arrowdown") { setVolume(video.volume - 0.1); }
  else return;
  e.preventDefault();
  poke();
});
$("channel").addEventListener("change", (e) => {
  const was = !!player;
  stop();
  channelId = e.target.value;
  history.replaceState(null, "", "#" + channelId);
  setPoster();
  render();
  if (was) watch();
});
// Leaving the page stops the stream, so the encoder can idle out.
window.addEventListener("pagehide", stop);

// ---------- status ----------
function renderRundown(s) {
  const root = $("rundown");
  root.replaceChildren();
  if (!s.rundown.length) { root.append(el("div", "empty", "No stories yet - waiting for the first fetch.")); return; }
  for (const seg of s.rundown) {
    root.append(el("div", "seg", seg.segment));
    const list = el("div");
    for (const st of seg.stories) {
      const row = el("div", "story");
      row.append(el("div", "t", st.title));
      if (st.summary) row.append(el("div", "s", st.summary));
      const m = el("div", "m");
      if (st.breaking) m.append(el("span", "brk", "BREAKING"));
      for (const o of st.outlets) m.append(el("span", "o", o));
      if (st.when) m.append(el("span", null, ago(st.when)));
      row.append(m);
      list.append(row);
    }
    root.append(list);
  }
  const n = s.rundown.reduce((a, g) => a + g.stories.length, 0);
  $("rd-sub").textContent = `${n} stories · updated ${clock(s.last_refresh)}`;
}

function renderOnAir(s) {
  const ch = channel();
  const kv = $("onair");
  kv.replaceChildren();
  const row = (k, v, cls) => { kv.append(el("dt", null, k)); const d = el("dd", cls); if (v instanceof Node) d.append(v); else d.textContent = v; kv.append(d); };
  const state = el("span");
  state.append(el("span", "dot" + (ch.running ? "" : " off")), ch.running ? "Encoding" : "Idle - starts when someone tunes in");
  row("Channel", label(ch));
  row("State", state);
  row("Viewers", String(ch.viewers));
  // The server reports what it is drawing, which is the buffer (~10 s) ahead of the screen.
  if (ch.running && ch.on_air) row("Up next", ch.on_air);
  if (ch.running && ch.seconds_ahead != null) row("Buffer", `${ch.seconds_ahead.toFixed(1)} s ahead`);
  if (ch.lead_reached_after != null) row("Tune-in", `${ch.lead_reached_after} s to buffer`);
  row("Sessions", `${ch.sessions}` + (ch.last_stop ? ` · last stop ${clock(ch.last_stop)}` : ""));
  row("Next fetch", s.last_refresh ? clock(new Date(Date.parse(s.last_refresh) + s.refresh_minutes * 60000).toISOString()) : "-");
  if (s.refresh_error) row("Error", s.refresh_error, "err");
  $("nowline").textContent = label(ch) + (ch.viewers > 1 ? ` · ${ch.viewers} watching` : "");
}

function renderAlerts(s) {
  const root = $("alerts");
  root.replaceChildren();
  const r = s.breaking_rule;
  $("br-sub").textContent = r.enabled ? `${r.min_sources}+ outlets / ${r.window_minutes} min` : "off";
  if (!s.alerts.length) { root.append(el("div", "empty", "None in the last 3 days.")); return; }
  for (const a of s.alerts) {
    const row = el("div", "alert");
    row.append(el("div", "w", ago(a.when).toUpperCase()), el("div", null, a.title));
    root.append(row);
  }
}

function renderFeeds(s) {
  const root = $("feeds");
  root.replaceChildren();
  const feeds = [...s.feeds].sort((a, b) => (!!b.error - !!a.error) || a.name.localeCompare(b.name));
  const bad = feeds.filter((f) => f.error).length;
  $("feeds-sub").textContent = bad ? `${bad} failing` : `${feeds.length} ok`;
  $("feeds-sub").className = "sub" + (bad ? " err" : "");
  for (const f of feeds) {
    const row = el("div", "feed" + (f.error ? " bad" : ""));
    const n = el("div", "n");
    n.append(el("span", "dot" + (f.error ? " bad" : f.enabled ? "" : " off")), f.name + " ", el("span", "h", f.host || ""));
    row.append(n, el("div", "c", f.error ? "FAILING" : `${f.stories}`));
    if (f.error) row.title = f.error;
    root.append(row);
  }
}

function render() {
  if (!status) return;
  if (!status.channels.length) {          // every channel is show_on = "tv"
    $("msg").textContent = "NO CHANNELS ARE SHOWN ON THE WEB (show_on)";
    box.classList.add("error");
    $("bigplay").hidden = true;
    return;
  }
  const ch0 = channel();       // the page takes the channel's look (auto Classic: light by day, dark at night)
  document.documentElement.dataset.look = ch0.look || ch0.theme;
  const sel = $("channel");
  if (status.channels.length > 1) {
    sel.hidden = false;
    if (sel.options.length !== status.channels.length) {
      sel.replaceChildren(...status.channels.map((c) => { const o = el("option", null, label(c)); o.value = c.id; return o; }));
    }
    sel.value = channel().id;
  }
  renderOnAir(status);
  renderRundown(status);
  renderAlerts(status);
  renderFeeds(status);
  $("ver").textContent = "anchorless " + status.version;
  const ch = channel();
  $("bighint").textContent = ch.running ? "already on - joins instantly" : "starts the channel - about 2 s";
  const live = ch.running && ch.viewers > 0;
  $("conn").textContent = live ? `ON AIR · ${ch.viewers} watching` : "STANDING BY";
  $("conn").className = "pill" + (live ? " live" : " ok");
}

async function refresh() {
  try {
    const r = await fetch("/api/status", { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    const first = !status;
    status = await r.json();
    if (first) {
      const want = location.hash.slice(1);
      channelId = status.channels.some((c) => c.id === want) ? want : status.channels[0]?.id;
      setPoster();
    }
    render();
  } catch (e) {
    $("conn").textContent = "OFFLINE";
    $("conn").className = "pill";
  }
}

$("fsicon").innerHTML = ICON.fs;
setMuted(false);
refresh();
setInterval(refresh, 5000);
setInterval(() => { if (!player) setPoster(); }, 30000);
