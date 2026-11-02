"use strict";
const $ = (id) => document.getElementById(id);
const el = (tag, attrs, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") e.className = v;
    else if (k === "style") e.style.cssText = v;          // CSSOM: allowed by the page's Content-Security-Policy
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v === true) e.setAttribute(k, "");
    else if (v !== false && v != null) e.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k != null) e.append(k instanceof Node ? k : document.createTextNode(String(k)));
  return e;
};
const clone = (x) => JSON.parse(JSON.stringify(x));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

let orig = null;     // the settings as loaded
let cur = null;      // what the page shows now (edited)

async function api(method, url, body) {
  const r = await fetch(url, { method, headers: { "Content-Type": "application/json", "X-Anchorless": "1" },
                               body: body ? JSON.stringify(body) : undefined, credentials: "same-origin" });
  let data = {};
  try { data = await r.json(); } catch (e) { /* empty */ }
  return { status: r.status, data };
}

function toast(text, bad) {
  const t = $("toast");
  t.textContent = text; t.className = "toast" + (bad ? " err" : ""); t.style.display = "block";
  clearTimeout(t._h); t._h = setTimeout(() => (t.style.display = "none"), bad ? 9000 : 4500);
}

// ---------- states: disabled, forbidden, login ----------
function showState(node) { $("state").replaceChildren(node); $("main").hidden = true; }

function showLogin(note) {
  const pw = el("input", { type: "password", id: "pw", autocomplete: "current-password", placeholder: "Password" });
  const msg = el("div", { class: "msg err" }, note || "");
  const form = el("form", { onsubmit: async (e) => {
      e.preventDefault();
      const r = await api("POST", "/api/login", { password: pw.value });
      if (r.status === 200) load();
      else msg.textContent = r.data.error || "could not log in";
    } }, pw, el("button", { class: "btn primary", type: "submit" }, "LOG IN"), msg);
  showState(el("div", { class: "card login" }, el("h2", {}, "LOG IN"),
    el("p", { class: "page-note" }, "The settings change the station for everyone."), form));
  pw.focus();
}

async function load() {
  const r = await api("GET", "/api/settings");
  if (r.status === 404 && r.data.error === "disabled") {
    return showState(el("div", { class: "card" }, el("h2", {}, "SETTINGS ARE OFF"),
      el("p", {}, "Set a password to turn the settings page on, best from the environment:"),
      el("pre", {}, "ANCHORLESS__ADMIN__PASSWORD=<a long random password>"),
      el("p", { class: "page-note" }, "Then restart Anchorless. Everything else on this port stays open; only the settings need the password.")));
  }
  if (r.status === 404) return showState(el("div", { class: "card" }, el("h2", {}, "NO CONFIG FILE"),
      el("p", {}, "Anchorless was started without a config file, so there is nothing to edit.")));
  if (r.status === 403 && r.data.error === "https required") {
    const https = "https://" + location.host + "/settings";
    return showState(el("div", { class: "card" }, el("h2", {}, "USE HTTPS"),
      el("p", {}, "The settings page only works over https, so your password is never sent unencrypted."),
      el("p", {}, "Open it through your https address (your reverse proxy), e.g. ", el("a", { href: https }, https), "."),
      el("p", { class: "page-note" }, "No reverse proxy? Open it on the server itself (localhost), or set [admin] require_https = false in the config file.")));
  }
  if (r.status === 403) return showState(el("div", { class: "card" }, el("h2", {}, "NOT ALLOWED"),
      el("p", {}, r.data.error || "forbidden"), el("p", { class: "page-note" }, "See [admin] allow_from in the config file.")));
  if (r.status === 401) return showLogin();
  if (r.status !== 200) return showState(el("div", { class: "card" }, el("h2", {}, "ERROR"), el("p", {}, JSON.stringify(r.data))));
  orig = r.data;
  orig.feeds.forEach((f, i) => (f._key = "f" + i));   // to match edits to the loaded list
  cur = clone(orig);
  $("logout").hidden = false;
  $("state").replaceChildren();
  $("main").hidden = false;
  render();
}

$("logout").addEventListener("click", async () => { await api("POST", "/api/logout"); location.reload(); });

// ---------- rendering ----------
function render() {
  document.documentElement.dataset.look = lookOf(cur.channels[0]);
  $("where").replaceChildren("Saved to ", el("code", {}, cur.config_path),
    ...(cur.local_path ? [" (local feeds: ", el("code", {}, cur.local_path), ")"] : []),
    ". You can still edit the file by hand: changes there show up here within a few seconds.");
  $("banner").replaceChildren(...(cur.config_error ? [el("div", { class: "banner" },
    "The config file was changed by hand and is not valid, so Anchorless is still running the last good version:\n" + cur.config_error)] : []));
  renderLookNote();
  renderChannels();
  renderSections();
  renderHistory();
  renderHeadlines();
  renderFileOnly();
  updateSaveBar();
}

function scalarInput(f, value, onchange) {
  const dis = !!f.locked;
  if (f.type === "boolean") {
    const box = el("input", { type: "checkbox", disabled: dis });
    box.checked = !!value;
    box.addEventListener("change", () => onchange(box.checked));
    return el("label", { class: "switch" }, box, el("span"));
  }
  if (f.enum) {
    const s = el("select", { disabled: dis }, f.enum.map((v) => el("option", { value: String(v) }, String(v))));
    s.value = String(value);
    s.addEventListener("change", () => onchange(f.type === "integer" ? parseInt(s.value, 10) : s.value));
    return s;
  }
  if (f.type === "integer" || f.type === "number") {
    const min = f.minimum ?? f.exclusiveMinimum, max = f.maximum ?? f.exclusiveMaximum;
    const i = el("input", { type: "number", disabled: dis, min: min ?? false, max: max ?? false, step: f.type === "integer" ? 1 : "any" });
    i.value = value;
    i.addEventListener("input", () => onchange(i.value === "" ? null : (f.type === "integer" ? parseInt(i.value, 10) : parseFloat(i.value))));
    return i;
  }
  if (f.type === "list") {
    const t = el("textarea", { disabled: dis });
    t.value = (value || []).join("\n");
    t.addEventListener("input", () => onchange(t.value.split("\n").map((x) => x.trim()).filter(Boolean)));
    return t;
  }
  const i = el("input", { type: "text", disabled: dis });
  i.value = value ?? "";
  i.addEventListener("input", () => onchange(i.value));
  return i;
}

function fieldOf(key, list) {
  for (const s of list) for (const f of s.fields) if (f.key === key) return f;
  return null;
}

function renderSections() {
  const root = $("sections");
  root.replaceChildren();
  for (const sec of cur.sections) {
    const card = el("div", { class: "card" }, el("h2", {}, sec.title.toUpperCase()));
    for (const f of sec.fields) {
      const o = fieldOf(f.key, orig.sections);
      const input = scalarInput(f, f.value, (v) => { f.value = v; mark(); });
      const mark = () => {
        const d = !same(f.value, o.value);
        (input.querySelector?.("input") || input).classList.toggle("dirty", d);
        updateSaveBar();
      };
      const right = el("div", {}, input,
        f.help ? el("div", { class: "h" }, f.help) : null,
        f.locked ? el("div", { class: "lock" }, f.lock_note || (f.locked === "environment" ? "SET BY THE ENVIRONMENT - CHANGE IT THERE" : "SET IN THE FILE - CHANGE IT THERE")) : null);
      card.append(el("div", { class: "field" },
        el("label", { class: "l" }, f.label, f.applies === "restart" ? el("span", { class: "rs", title: "Applying this restarts the channels' streams" }, "↻") : null),
        right));
      mark();
    }
    if (sec.id === "rundown") card.append(renderSegments());
    if (sec.id === "feeds") card.append(renderFeeds());
    root.append(card);
  }
}

// ---------- channels ----------
const LOOKS = { "studio": "Studio", "classic": "Classic (auto)", "classic-light": "Classic light", "classic-dark": "Classic dark" };
// The look a theme has now: auto Classic is light by day and dark at night (the server says which).
function lookOf(ch) { return ch?.theme === "classic" ? cur.classic_now : (ch?.theme || "studio"); }
function renderLookNote() {
  const main = cur.channels[0];
  const auto = main.theme === "classic"
    ? [" - light from 6:00 to 19:00, dark at night; it is ", el("b", {}, lookOf(main) === "classic-dark" ? "dark" : "light"), " now"] : [];
  $("look-note").replaceChildren("These web pages take the ", el("b", {}, "main channel's"), " look: ",
    el("b", {}, LOOKS[main.theme] || main.theme), " (", main.name, ")", ...auto,
    ". Change the main channel's theme below to change it; the viewer page follows whichever channel you watch.");
}
function liveOf(id) { return orig.live[id] || { viewers: 0, running: false, pending: false }; }

function renderChannels() {
  const root = $("channels");
  root.replaceChildren();
  cur.channels.forEach((ch) => {
    const o = orig.channels.find((x) => x.id === ch.id && !ch._new);
    const row = el("div", { class: "row" + (ch._removed ? " removed" : "") + (ch._new ? " new" : "") });
    const dis = (f) => ch._removed || (ch.locked || []).includes(f);
    const theme = el("select", { disabled: dis("theme"), title: ch.main ? "Also the look of these web pages" : "" },
      cur.themes.map((t) => el("option", { value: t }, LOOKS[t] || t)));
    theme.value = ch.theme;
    const name = el("input", { type: "text", class: "grow", disabled: dis("name"), placeholder: "Name" });
    name.value = ch.name || "";
    const show = el("select", { disabled: dis("show_on") },
      [["both", "TV + web"], ["tv", "TV only"], ["web", "Web only"]].map(([v, t]) => el("option", { value: v }, t)));
    show.value = ch.show_on;
    const num = el("input", { type: "text", size: 5, placeholder: "No.", disabled: dis("channel_number") || ch.show_on === "web",
                               title: "Channel number (ignored for web only)" });
    num.value = ch.show_on === "web" ? "" : (ch.channel_number ?? "");
    const markAll = () => {
      for (const [inp, f] of [[theme, "theme"], [name, "name"], [show, "show_on"], [num, "channel_number"]]) {
        inp.classList.toggle("dirty", !!o && String(o[f] ?? "") !== String(ch[f] ?? ""));
      }
      updateSaveBar();
    };
    theme.addEventListener("change", () => { ch.theme = theme.value; if (ch.main) { document.documentElement.dataset.look = lookOf(ch); renderLookNote(); } markAll(); });
    name.addEventListener("input", () => { ch.name = name.value; markAll(); });
    show.addEventListener("change", () => { ch.show_on = show.value; num.disabled = show.value === "web" || dis("channel_number");
                                            if (show.value !== "web" && !num.value && o?.channel_number) num.value = ch.channel_number = o.channel_number; markAll(); });
    num.addEventListener("input", () => { ch.channel_number = num.value.trim() || null; markAll(); });
    const live = liveOf(ch.id);
    row.append(el("span", { class: "k" }, ch.main ? "MAIN" : (ch._new ? "NEW" : "EXTRA")), theme, name, show, num);
    if (!ch._new) row.append(el("span", { class: "tag" + (live.running ? " on" : "") }, live.running ? `${live.viewers} WATCHING` : "IDLE"));
    if (live.pending) row.append(el("span", { class: "tag warn", title: "Saved settings apply when nobody is watching" }, "CHANGES WAITING"));
    if (!ch.main) {
      row.append(el("button", { class: "btn small", onclick: () => {
        if (ch._new) cur.channels.splice(cur.channels.indexOf(ch), 1); else ch._removed = !ch._removed;
        renderChannels(); updateSaveBar(); } }, ch._removed ? "UNDO" : "REMOVE"));
    }
    root.append(row);
    markAll();
  });
}

$("add-channel").addEventListener("click", () => {
  const used = new Set(cur.channels.map((c) => c.name));
  let n = 2; while (used.has(`NEWS ${n}`)) n++;
  cur.channels.push({ _new: true, main: false, id: null, theme: "classic", name: `NEWS ${n}`, show_on: "web", channel_number: null });
  renderChannels(); updateSaveBar();
});

// ---------- segments ----------
function renderSegments() {
  const box = el("div", { class: "field" }, el("label", { class: "l" }, "Segments"));
  const list = el("div", { class: "rows" });
  const redraw = () => {
    list.replaceChildren();
    cur.segments.forEach((s, i) => {
      const name = el("input", { type: "text", class: "grow", value: s.name, title: "{city} becomes the local segment's city" });
      name.addEventListener("input", () => { s.name = name.value; updateSaveBar(); });
      const n = el("input", { type: "number", min: 1, max: 20, value: s.stories ?? 3, style: "width:64px", title: "Stories" });
      n.addEventListener("input", () => { s.stories = parseInt(n.value, 10) || 1; updateSaveBar(); });
      const scope = el("select", {}, [["", "any scope"], ...cur.scopes.map((x) => [x, x])].map(([v, t]) => el("option", { value: v }, t)));
      scope.value = s.scope || "";
      scope.addEventListener("change", () => { s.scope = scope.value || undefined; if (!s.scope) delete s.scope; updateSaveBar(); });
      const cat = el("input", { type: "text", placeholder: "any category", value: s.category || "", style: "width:120px" });
      cat.addEventListener("input", () => { if (cat.value.trim()) s.category = cat.value.trim(); else delete s.category; updateSaveBar(); });
      const noLocal = el("input", { type: "checkbox" });
      noLocal.checked = (s.exclude_scope || []).includes("local");
      noLocal.addEventListener("change", () => { if (noLocal.checked) s.exclude_scope = ["local"]; else delete s.exclude_scope; updateSaveBar(); });
      const move = (d) => { const j = i + d; if (j < 0 || j >= cur.segments.length) return;
        [cur.segments[i], cur.segments[j]] = [cur.segments[j], cur.segments[i]]; redraw(); updateSaveBar(); };
      list.append(el("div", { class: "row" }, name, el("span", { class: "k" }, "STORIES"), n, scope, cat,
        el("label", { class: "k", title: "Leave out stories only local outlets carry" }, noLocal, " NO LOCAL-ONLY"),
        el("button", { class: "btn small", onclick: () => move(-1), title: "Earlier" }, "▲"),
        el("button", { class: "btn small", onclick: () => move(1), title: "Later" }, "▼"),
        el("button", { class: "btn small", onclick: () => { cur.segments.splice(i, 1); redraw(); updateSaveBar(); } }, "✕")));
    });
    list.append(el("div", {}, el("button", { class: "btn small", onclick: () => {
      cur.segments.push({ name: "NEW SEGMENT", stories: 3 }); redraw(); updateSaveBar(); } }, "+ ADD SEGMENT")));
  };
  redraw();
  box.append(el("div", {}, list, el("div", { class: "h" }, "Played in this order, then the loop starts again. A story appears in the first segment it fits.")));
  return box;
}

// ---------- feeds ----------
// The full status (exact errors), which only this page gets.
function statusFor(f) { return cur.feed_status?.[f.url]; }

function renderFeeds() {
  const wrap = el("div", { class: "field" }, el("label", { class: "l" }, "Feeds"));
  const body = el("div");
  const builtinOn = fieldOf("feeds.builtin", cur.sections).value;
  const groups = [["builtin", "BUILT-IN"], ["config", "YOUR FEEDS"], ["local", "LOCAL (kept in the local feeds file)"]];
  for (const [origin, title] of groups) {
    const feeds = cur.feeds.filter((f) => f.origin === origin);
    if (!feeds.length && origin === "builtin") continue;
    body.append(el("div", { class: "feed-group" }, title));
    if (!feeds.length) body.append(el("div", { class: "h" }, "None yet."));
    for (const f of feeds) body.append(feedRow(f, origin === "builtin" && !builtinOn));
  }
  body.append(addFeedBox());
  wrap.append(body);
  return wrap;
}

function feedRow(f, forcedOff) {
  const o = orig.feeds.find((x) => x._key === f._key);
  const box = el("input", { type: "checkbox", disabled: forcedOff || f._removed });
  box.checked = f.enabled && !forcedOff;
  box.addEventListener("change", () => { f.enabled = box.checked; box.classList.toggle("dirty", !!o && o.enabled !== f.enabled); updateSaveBar(); });
  if (o && o.enabled !== f.enabled) box.classList.add("dirty");
  const st = statusFor(o || f);
  const info = el("div", {}, el("div", {}, f.name, " ", el("span", { class: "row tag" + (st?.error ? " bad" : ""), style: "padding:1px 5px;display:inline;border:0" },
      f.origin === "local" ? "local" : f.scope, f.category !== "general" ? " · " + f.category : "",
      st ? (st.error ? " · FAILING" : ` · ${st.stories} stories`) : "")),
    el("div", { class: "u" }, f.url),
    st?.error ? el("div", { class: "u err" }, st.error) : null);
  const acts = el("div", { class: "acts" });
  if (f.origin !== "builtin") {
    acts.append(el("button", { class: "btn small", onclick: () => editFeed(f, row) }, "EDIT"),
      el("button", { class: "btn small", onclick: () => { if (f._new) cur.feeds.splice(cur.feeds.indexOf(f), 1); else f._removed = !f._removed; renderSections(); updateSaveBar(); } },
        f._removed ? "UNDO" : "REMOVE"));
  }
  const row = el("div", { class: "feed-row" + (f._removed ? " removed" : "") }, el("label", { class: "switch" }, box, el("span")), info, acts);
  if (f._removed) row.style.opacity = ".45";
  return row;
}

function editFeed(f, row) {
  const name = el("input", { type: "text", value: f.name, placeholder: "Outlet name (shown on screen)" });
  const url = el("input", { type: "url", value: f.url, class: "grow", placeholder: "https://…" });
  const scope = el("select", {}, ["national", "world"].map((x) => el("option", { value: x }, x)));
  scope.value = f.scope === "world" ? "world" : "national";
  const cat = el("input", { type: "text", value: f.category === "general" ? "" : f.category, placeholder: "category (e.g. business)", style: "width:170px" });
  const out = el("span", { class: "check-out" });
  const box = el("div", { class: "addbox" },
    el("div", { class: "line" }, name, url),
    el("div", { class: "line" }, f.origin === "local" ? el("span", { class: "k" }, "LOCAL") : scope, cat,
      el("button", { class: "btn small", onclick: () => checkFeed(url.value, name.value, out) }, "CHECK FEED"),
      el("button", { class: "btn small primary", onclick: () => {
        f.name = name.value.trim(); f.url = url.value.trim(); if (f.origin !== "local") f.scope = scope.value;
        f.category = cat.value.trim() || "general"; f._edited = true; renderSections(); updateSaveBar(); } }, "OK"),
      el("button", { class: "btn small", onclick: () => renderSections() }, "CANCEL"), out));
  row.replaceWith(box);
}

async function checkFeed(url, name, out) {
  out.className = "check-out"; out.textContent = "checking…";
  const r = await api("POST", "/api/feeds/check", { url, name });
  if (r.status !== 200) { out.className = "check-out err"; out.textContent = r.data.error || "check failed"; return false; }
  if (r.data.ok) { out.className = "check-out ok"; out.textContent = `✓ ${r.data.stories} stories - newest: "${r.data.newest}"`; return true; }
  out.className = "check-out err"; out.textContent = "✗ " + r.data.error;
  return false;
}

function addFeedBox() {
  const name = el("input", { type: "text", placeholder: "Outlet name (shown on screen)" });
  const url = el("input", { type: "url", class: "grow", placeholder: "Feed URL: https://…" });
  const where = el("select", {}, [["national", "national"], ["world", "world"], ["local", "local"]].map(([v, t]) => el("option", { value: v }, t)));
  const cat = el("input", { type: "text", placeholder: "category (optional)", style: "width:170px" });
  const out = el("span", { class: "check-out" });
  return el("div", { class: "addbox" }, el("div", { class: "k" }, "ADD A FEED"),
    el("div", { class: "line" }, name, url),
    el("div", { class: "line" }, where, cat,
      el("button", { class: "btn small", onclick: () => checkFeed(url.value, name.value, out) }, "CHECK FEED"),
      el("button", { class: "btn small primary", onclick: async () => {
        if (!name.value.trim() || !/^https?:\/\//.test(url.value.trim())) { out.className = "check-out err"; out.textContent = "needs a name and an http(s) URL"; return; }
        const local = where.value === "local";
        cur.feeds.push({ _new: true, _key: "new" + Math.random(), origin: local ? "local" : "config", name: name.value.trim(), url: url.value.trim(),
                         scope: local ? "local" : where.value, category: cat.value.trim() || "general", enabled: true });
        renderSections(); updateSaveBar(); } }, "ADD"), out),
    el("div", { class: "h" }, "Check it first: it fetches the feed once and shows what it found. Added feeds start with the next fetch after saving."));
}

// ---------- recent changes ----------
function changeLabel(key) {
  const f = fieldOf(key, cur.sections);
  if (f) return f.label;
  let m = key.match(/^channel (.+)\.(\w+)$/);
  if (m) { const ch = cur.channels.find((c) => c.id === m[1]); return `${ch ? ch.name : m[1]} ${m[2].replace("_", " ")}`; }
  m = key.match(/^feed (.+)$/);
  if (m) {
    let where = m[1];
    try { const u = new URL(m[1]); where = u.hostname + u.pathname; } catch (e) { /* keep it as is */ }
    return "Feed " + where;
  }
  if (key === "rundown.segment") return "Segments";
  return key;
}

function renderHistory() {
  const root = $("history");
  root.replaceChildren();
  if (!cur.history?.length) { root.append(el("div", { class: "h" }, "No changes yet.")); return; }
  const show = (v) => (v === null || v === undefined || v === "" ? "-" : Array.isArray(v) ? v.join(", ") : String(v));
  for (const h of cur.history) {
    const when = new Date(h.when).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
    root.append(el("div", { class: "hist" },
      el("div", { class: "w" }, `${when.toUpperCase()} · ${h.source.toUpperCase()}`),
      el("ul", {}, h.changes.map((c) => el("li", {}, changeLabel(c.key), ": ",
        c.old === null || c.old === undefined ? "" : el("span", { class: "old" }, show(c.old)),
        c.old === null || c.old === undefined ? "added " : " → ", show(c.new))))));
  }
}

// ---------- headline choices ----------
function renderHeadlines() {
  const root = $("headlines");
  root.replaceChildren();
  const log = cur.headline_log || [];
  if (!log.length) {
    root.append(el("div", { class: "h" }, fieldOf("rundown.headline_choice", cur.sections)?.value === "first"
      ? "Off (\"first\")." : "None since the last restart: every story kept its first-published headline."));
    return;
  }
  for (const h of log) {
    const when = new Date(h.when).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
    root.append(el("div", { class: "hist" },
      el("div", { class: "w" }, `${when.toUpperCase()} · ${h.mode === "log" ? "WOULD SHOW" : "SHOWING"}`),
      el("div", {}, `${h.shown.title}`, el("span", { class: "h" }, ` (${h.shown.outlet})`)),
      el("div", {}, el("span", { class: "old" }, h.instead_of.title), el("span", { class: "h" }, ` (${h.instead_of.outlet})`)),
      el("div", { class: "h" }, h.why)));
  }
}

// ---------- file only ----------
function renderFileOnly() {
  const root = $("fileonly");
  root.replaceChildren();
  for (const [sec, values] of Object.entries(cur.file_only)) {
    root.append(el("div", { class: "ro-sec" }, `[${sec}]`));
    const dl = el("dl", { class: "ro" });
    for (const [k, v] of Object.entries(values)) dl.append(el("dt", {}, k), el("dd", {}, v === null ? "-" : (typeof v === "object" ? JSON.stringify(v) : String(v))));
    root.append(dl);
  }
}

// ---------- changes -> operations ----------
function ops() {
  const out = [];
  for (const sec of cur.sections) for (const f of sec.fields) {
    const o = fieldOf(f.key, orig.sections);
    if (!same(f.value, o.value)) out.push({ op: "set", key: f.key, old: o.value, value: f.value, _label: f.label, _restart: f.applies === "restart" });
  }
  for (const ch of cur.channels) {
    if (ch._new) { out.push({ op: "add_channel", value: { theme: ch.theme, name: ch.name, show_on: ch.show_on, channel_number: ch.channel_number }, _label: `add channel ${ch.name}`, _restart: true }); continue; }
    if (ch._removed) { out.push({ op: "remove_channel", id: ch.id, _label: `remove channel ${ch.name}`, _restart: true }); continue; }
    const o = orig.channels.find((x) => x.id === ch.id);
    const value = {}, old = {};
    for (const f of ["theme", "name", "show_on", "channel_number"]) {
      if (String(o[f] ?? "") !== String(ch[f] ?? "")) { value[f] = ch[f]; old[f] = o[f]; }
    }
    if (Object.keys(value).length) out.push({ op: "channel", id: ch.id, old, value, _label: `${o.name}: ${Object.keys(value).join(", ")}`,
                                              _restart: "theme" in value || "name" in value, _channel: ch.id });
  }
  const segClean = (l) => l.map((s) => Object.fromEntries(Object.entries(s).filter(([, v]) => v !== undefined)));
  if (!same(segClean(cur.segments), orig.segments)) out.push({ op: "segments", old: orig.segments, value: segClean(cur.segments), _label: "segments" });
  for (const f of cur.feeds) {
    if (f._new) { out.push({ op: "feed_add", origin: f.origin, value: { name: f.name, url: f.url, scope: f.scope, category: f.category }, _label: `add feed ${f.name}` }); continue; }
    const o = orig.feeds.find((x) => x._key === f._key);
    if (f._removed) { out.push({ op: "feed_remove", origin: f.origin, url: o.url, _label: `remove feed ${o.name}` }); continue; }
    if (f._edited && (f.name !== o.name || f.url !== o.url || f.scope !== o.scope || f.category !== o.category)) {
      out.push({ op: "feed_edit", origin: f.origin, url: o.url, old: { name: o.name, url: o.url, scope: o.scope, category: o.category },
                 value: { name: f.name, url: f.url, scope: f.scope, category: f.category }, _label: `edit feed ${o.name}` });
    }
    if (f.enabled !== o.enabled) out.push({ op: "feed_toggle", origin: f.origin, url: o.url, old: o.enabled, value: f.enabled, _label: `${o.name} ${f.enabled ? "on" : "off"}` });
  }
  return out;
}

function updateSaveBar() {
  if (!cur) return;
  const list = ops();
  $("savebar").classList.toggle("show", list.length > 0);
  if (!list.length) return;
  $("sum").replaceChildren(el("b", {}, `${list.length} CHANGE${list.length > 1 ? "S" : ""}`), " ", list.map((o) => o._label).join(" · "));
  // Which running channels a save would restart.
  const all = list.some((o) => o._restart && o.op === "set");
  const hit = cur.channels.filter((c) => !c._new && (all || list.some((o) => o._channel === c.id && o._restart)));
  const watched = hit.filter((c) => liveOf(c.id).running);
  const ap = $("apply");
  ap.replaceChildren();
  if (watched.length) {
    const viewers = watched.reduce((n, c) => n + liveOf(c.id).viewers, 0);
    ap.append(
      el("label", {}, el("input", { type: "radio", name: "apply", value: "idle", checked: true }), ` Restart ${watched.map((c) => c.name).join(", ")} when nobody is watching`),
      el("label", {}, el("input", { type: "radio", name: "apply", value: "now" }), ` Restart now (${viewers} watching - they reconnect in ~2 s)`));
  }
}

$("discard").addEventListener("click", () => { cur = clone(orig); render(); });

$("save").addEventListener("click", async () => {
  const list = ops();
  if (!list.length) return;
  const apply = document.querySelector('input[name="apply"]:checked')?.value || "idle";
  const body = { apply, ops: list.map((o) => Object.fromEntries(Object.entries(o).filter(([k]) => !k.startsWith("_")))) };
  $("save").disabled = true;
  const r = await api("PATCH", "/api/settings", body);
  $("save").disabled = false;
  if (r.status === 200) {
    const parts = [];
    if (r.data.restarted?.length) parts.push("restarted " + r.data.restarted.join(", "));
    if (r.data.pending?.length) parts.push(r.data.pending.join(", ") + " will restart when nobody is watching");
    if (r.data.added?.length) parts.push("added " + r.data.added.join(", "));
    if (r.data.removed?.length) parts.push("removed " + r.data.removed.join(", "));
    toast("Saved." + (parts.length ? " " + parts.join("; ") + "." : " Applied."));
    load();
  } else if (r.status === 401) {
    showLogin("Your login expired - log in again (your changes were not saved).");
  } else if (r.status === 409) {
    toast("Not saved: " + r.data.error + ". Reload to see the current values.", true);
    $("sum").append(" ", el("button", { class: "btn small", onclick: () => load() }, "RELOAD"));
  } else {
    toast("Not saved: " + (r.data.error || r.status), true);
  }
});

window.addEventListener("beforeunload", (e) => { if (cur && ops().length) { e.preventDefault(); e.returnValue = ""; } });

load();
