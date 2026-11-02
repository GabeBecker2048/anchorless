import asyncio

import pytest

from anchorless.config import parse_config
from anchorless.settings import Conflict, Invalid, Settings, SettingsError

CONFIG = '''# My station.
[channel]
theme = "studio"
show_on = "both"
channel_number = 2            # the official news channel

[rundown]
page_seconds = 12             # long enough to read

[data]
dir = "{data}"
'''


@pytest.fixture
def cfg_file(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(CONFIG.replace("{data}", str(tmp_path / "data")))
    return p


def patch(st, *ops):
    return asyncio.run(st.patch(list(ops)))


def test_a_change_keeps_comments_and_everything_else(cfg_file):
    st = Settings(cfg_file, environ={})
    before = cfg_file.read_text()
    patch(st, {"op": "set", "key": "rundown.page_seconds", "old": 12.0, "value": 9})
    after = cfg_file.read_text()
    assert "page_seconds = 9             # long enough to read" in after
    changed = [(a, b) for a, b in zip(before.splitlines(), after.splitlines(), strict=True) if a != b]
    assert len(changed) == 1 and changed[0][0].startswith("page_seconds = 12")   # only that line
    assert not [p for p in cfg_file.parent.iterdir() if p.name.startswith(".")]   # no temp files left


def test_someone_elses_change_is_a_conflict_not_an_overwrite(cfg_file):
    st = Settings(cfg_file, environ={})
    patch(st, {"op": "set", "key": "rundown.page_seconds", "old": 12.0, "value": 9})
    with pytest.raises(Conflict) as err:     # a second page still thinks it is 12
        patch(st, {"op": "set", "key": "rundown.page_seconds", "old": 12.0, "value": 20},
              {"op": "set", "key": "breaking.min_sources", "old": 4, "value": 6})
    assert err.value.keys == ["rundown.page_seconds"]
    assert "min_sources" not in cfg_file.read_text()          # nothing from that save was written
    patch(st, {"op": "set", "key": "breaking.min_sources", "old": 4, "value": 6})   # unrelated: fine


def test_invalid_values_are_never_written(cfg_file):
    st = Settings(cfg_file, environ={})
    before = cfg_file.read_text()
    with pytest.raises(Invalid, match="page_seconds"):
        patch(st, {"op": "set", "key": "rundown.page_seconds", "old": 12.0, "value": 1})
    with pytest.raises(Invalid, match="channel_number is required"):
        patch(st, {"op": "add_channel", "value": {"theme": "classic", "name": "B", "show_on": "tv"}})
    assert cfg_file.read_text() == before


def test_file_only_and_environment_settings_cannot_be_changed(cfg_file):
    st = Settings(cfg_file, environ={"ANCHORLESS__BREAKING__MIN_SOURCES": "5"})
    with pytest.raises(SettingsError, match="only be changed in the file"):
        patch(st, {"op": "set", "key": "video.width", "old": 854, "value": 640})
    with pytest.raises(SettingsError, match="environment"):
        patch(st, {"op": "set", "key": "breaking.min_sources", "old": 5, "value": 6})
    field = next(f for s in st.snapshot()["sections"] for f in s["fields"] if f["key"] == "breaking.min_sources")
    assert field["locked"] == "environment" and field["value"] == 5


def test_channels_add_change_remove(cfg_file):
    st = Settings(cfg_file, environ={})
    patch(st, {"op": "add_channel", "value": {"theme": "classic", "name": "NEWS CLASSIC", "show_on": "web"}})
    chans = st.snapshot()["channels"]
    assert [c["id"] for c in chans] == ["anchorless.news", "anchorless.news-classic"]
    patch(st, {"op": "channel", "id": "anchorless.news-classic", "old": {"name": "NEWS CLASSIC", "show_on": "web"},
               "value": {"name": "CLASSIC", "show_on": "both", "channel_number": 97}})
    c = st.snapshot()["channels"][1]
    assert (c["id"], c["name"], c["channel_number"]) == ("anchorless.news-classic", "CLASSIC", "97")  # id kept
    patch(st, {"op": "remove_channel", "id": "anchorless.news-classic"})
    assert "extra_channel" not in cfg_file.read_text()


def test_feeds_on_off_add_and_local_feeds_stay_out_of_the_config(cfg_file):
    st = Settings(cfg_file, environ={})
    npr = "https://feeds.npr.org/1001/rss.xml"
    patch(st, {"op": "feed_toggle", "origin": "builtin", "url": npr, "old": True, "value": False},
          {"op": "feed_add", "origin": "local", "value": {"name": "Town TV", "url": "https://town.example/rss"}},
          {"op": "feed_add", "origin": "config", "value": {"name": "Wire", "url": "https://wire.example/rss", "scope": "world"}})
    text = cfg_file.read_text()
    assert npr in text and "wire.example" in text and "town.example" not in text
    assert "town.example" in (cfg_file.parent / "local.toml").read_text()
    feeds = {f["url"]: f for f in st.snapshot()["feeds"]}
    assert not feeds[npr]["enabled"] and feeds["https://town.example/rss"]["origin"] == "local"
    assert feeds["https://wire.example/rss"]["origin"] == "config" and len(feeds) == 23   # 21 built-in + 2
    with pytest.raises(SettingsError, match="http"):
        patch(st, {"op": "feed_add", "origin": "config", "value": {"name": "X", "url": "file:///etc/passwd"}})


def test_segments_are_written_in_order(cfg_file):
    st = Settings(cfg_file, environ={})
    segs = st.snapshot()["segments"]
    patch(st, {"op": "segments", "old": segs, "value": [segs[2], {"name": "ALL", "stories": 5}]})
    cfg = parse_config(cfg_file.read_text(), {}, path=cfg_file)
    assert [(s.name, s.stories) for s in cfg.rundown.segment] == [("NATIONAL", 3), ("ALL", 5)]


# --- the HTTP side: login, guards, live reload ---

def _app_test(cfg_file, environ, body):
    from aiohttp.test_utils import TestClient, TestServer

    from anchorless.config import load_config
    from anchorless.stream.server import make_app

    async def run():
        import os
        old = dict(os.environ)
        os.environ.update(environ)
        try:
            cfg = load_config(cfg_file)
            app = make_app(cfg, cfg_file)
            async with TestClient(TestServer(app)) as client:
                await body(client, app)
        finally:
            os.environ.clear()
            os.environ.update(old)

    asyncio.run(run())


W = {"X-Anchorless": "1"}


def test_settings_are_off_without_a_password(cfg_file):
    async def body(client, app):
        assert (await client.get("/api/settings")).status == 404
        assert (await client.get("/settings")).status == 200          # the page explains how to turn it on
        assert (await client.get("/playlist.m3u")).status == 200      # the TV side never needs a login
    _app_test(cfg_file, {}, body)


def test_login_guards_and_a_save_applies_live(cfg_file):
    async def body(client, app):
        assert (await client.get("/api/settings")).status == 401
        assert (await client.post("/api/login", json={"password": "secret"})).status == 403   # no X-Anchorless
        for _ in range(5):
            assert (await client.post("/api/login", json={"password": "nope"}, headers=W)).status == 401
        assert (await client.post("/api/login", json={"password": "secret"}, headers=W)).status == 429
        app["station"].settings  # noqa: B018 - the station has a settings editor
        client.session.cookie_jar.clear()
        # A fresh address-limit: reset the counter (as a minute passing would).
        from anchorless.stream import web as webmod  # noqa: F401
        for route in app.router.routes():
            handler = getattr(route.handler, "__self__", None)
            if handler is not None and hasattr(handler, "_fails"):
                handler._fails.clear()
        assert (await client.post("/api/login", json={"password": "secret"}, headers=W)).status == 200
        snap = await (await client.get("/api/settings")).json()
        assert "password" not in str(snap["sections"]) and snap["file_only"]["admin"]["password"] == "set"
        r = await client.patch("/api/settings", json={"ops": [
            {"op": "set", "key": "rundown.page_seconds", "old": 12.0, "value": 8}]})
        assert r.status == 403                                        # writes need the header
        r = await client.patch("/api/settings", headers={**W, "Origin": "http://evil.example"}, json={"ops": [
            {"op": "set", "key": "rundown.page_seconds", "old": 12.0, "value": 8}]})
        assert r.status == 403                                        # and the same origin
        r = await client.patch("/api/settings", headers=W, json={"ops": [
            {"op": "set", "key": "rundown.page_seconds", "old": 12.0, "value": 8},
            {"op": "add_channel", "value": {"theme": "classic", "name": "B", "show_on": "web"}}]})
        assert r.status == 200 and (await r.json())["added"] == ["B"]
        st = app["station"]
        assert st.cfg.rundown.page_seconds == 8                       # live, on the shared config
        assert list(st.channels) == ["anchorless.news", "anchorless.b"]
        assert "page_seconds = 8" in cfg_file.read_text()
        bad = await client.patch("/api/settings", headers=W, json={"ops": [
            {"op": "set", "key": "rundown.page_seconds", "old": 12.0, "value": 9}]})
        assert bad.status == 409
    _app_test(cfg_file, {"ANCHORLESS__ADMIN__PASSWORD": "secret"}, body)


def test_a_session_survives_a_restart(cfg_file):
    cookies = {}

    async def first(client, app):
        r = await client.post("/api/login", json={"password": "secret"}, headers=W)
        cookies.update({k: v.value for k, v in r.cookies.items()})

    async def second(client, app):
        r = await client.get("/api/settings", cookies=cookies)
        assert r.status == 200

    env = {"ANCHORLESS__ADMIN__PASSWORD": "secret"}
    _app_test(cfg_file, env, first)
    _app_test(cfg_file, env, second)


def test_a_hand_edit_is_picked_up(cfg_file):
    async def body(client, app):
        st = app["station"]
        cfg_file.write_text(cfg_file.read_text().replace("page_seconds = 12", "page_seconds = 7"))
        st.config_version = "stale"
        await asyncio.wait_for(_one_watch_round(st), 10)
        assert st.cfg.rundown.page_seconds == 7 and st.config_error is None
        cfg_file.write_text(cfg_file.read_text().replace("page_seconds = 7", "page_seconds = 1"))
        await asyncio.wait_for(_one_watch_round(st), 10)
        assert st.cfg.rundown.page_seconds == 7 and "page_seconds" in st.config_error   # kept the last good one
    _app_test(cfg_file, {}, body)


async def _one_watch_round(st):
    v = st.config_version
    while st.config_version == v:
        await asyncio.sleep(0.2)
    await asyncio.sleep(0.3)


# --- feeds stay on the public internet (SSRF) ---

def test_feed_urls_on_private_networks_are_refused():
    from anchorless.netguard import BlockedURL, check_url

    async def run():
        for url in ("http://192.168.1.1/", "http://10.0.0.5/rss", "http://127.0.0.1:9798/", "http://localhost/",
                    "http://100.101.102.103/", "http://169.254.169.254/latest/meta-data/", "http://[::1]/",
                    "http://[::ffff:192.168.1.1]/", "file:///etc/passwd", "gopher://x/"):
            with pytest.raises(BlockedURL):
                await check_url(url)
        await check_url("http://8.8.8.8/rss")                          # a public address
        await check_url("http://192.168.1.50/rss", allow_private=True)  # allowed when the file says so
    asyncio.run(run())


def test_a_redirect_into_the_lan_is_refused():
    import httpx

    from anchorless.netguard import BlockedURL, guard_hooks

    def handler(request):
        if request.url.host == "8.8.8.8":
            return httpx.Response(302, headers={"Location": "http://192.168.1.1/admin"})
        return httpx.Response(200, text="router admin")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True,
                                     event_hooks=guard_hooks(False)) as client:
            with pytest.raises(BlockedURL, match="private network"):
                await client.get("http://8.8.8.8/feed.xml")
    asyncio.run(run())


def test_the_settings_api_refuses_a_lan_feed(cfg_file):
    async def body(client, app):
        await client.post("/api/login", json={"password": "secret"}, headers=W)
        r = await client.patch("/api/settings", headers=W, json={"ops": [
            {"op": "feed_add", "origin": "config", "value": {"name": "Router", "url": "http://192.168.1.1/"}}]})
        assert r.status == 400 and "private network" in (await r.json())["error"]
        r = await client.post("/api/feeds/check", headers=W, json={"url": "http://127.0.0.1:9798/health"})
        assert not (await r.json())["ok"]
        assert "192.168.1.1" not in cfg_file.read_text()
    _app_test(cfg_file, {"ANCHORLESS__ADMIN__PASSWORD": "secret"}, body)


# --- https only ---

def test_login_needs_https_except_from_this_machine(cfg_file):
    cfg_file.write_text(cfg_file.read_text() + '\n[admin]\ntrusted_proxies = ["127.0.0.1"]\n')

    async def body(client, app):
        lan = {**W, "X-Forwarded-For": "192.168.1.50"}       # through the (trusted) proxy, from the LAN
        r = await client.post("/api/login", json={"password": "secret"}, headers={**lan, "X-Forwarded-Proto": "http"})
        assert r.status == 403 and (await r.json())["error"] == "https required"
        r = await client.post("/api/login", json={"password": "secret"}, headers={**lan, "X-Forwarded-Proto": "https"})
        assert r.status == 200 and "secure" in r.headers["Set-Cookie"].lower()
        # (A Secure cookie is only sent over https; this test client is plain http, so pass it on.)
        jar = {k: v.value for k, v in r.cookies.items()}
        ok = await client.get("/api/settings", headers={**lan, "X-Forwarded-Proto": "https"}, cookies=jar)
        assert ok.status == 200
        plain = await client.get("/api/settings", headers={**lan, "X-Forwarded-Proto": "http"}, cookies=jar)
        assert plain.status == 403
        client.session.cookie_jar.clear()
        assert (await client.post("/api/login", json={"password": "secret"}, headers=W)).status == 200   # localhost
    _app_test(cfg_file, {"ANCHORLESS__ADMIN__PASSWORD": "secret"}, body)
