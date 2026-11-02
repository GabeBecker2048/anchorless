"""Who may use the settings page, on the same port as everything else.

The TV side (/live.ts, /playlist.m3u, /guide.xml, ...) and the viewer page stay
open. The settings page and its API need, in order:

1. a password to exist at all ([admin] password, best from the environment as
   ANCHORLESS__ADMIN__PASSWORD, or [admin] password_hash from `anchorless
   hash-password`) - without one the settings page is switched off;
2. a client address in [admin] allow_from (default: this machine and private
   networks). Behind a reverse proxy listed in [admin] trusted_proxies, the
   address comes from X-Forwarded-For;
3. a session cookie from logging in. It is signed with a key made from the
   password and a random secret kept in the data folder, so sessions survive a
   restart and changing the password logs everyone out. Five wrong passwords a
   minute from one address and it waits;
4. for changes, a custom header (X-Anchorless: 1) that a form on another site
   cannot send, and an Origin header, when present, from this same host;
5. https ([admin] require_https, on by default): plain http would carry the
   password and the session unencrypted. "https" means a TLS connection, or a
   trusted proxy saying X-Forwarded-Proto: https. Localhost is exempt.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import logging
import os
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web

from ..config import Config
from ..passwords import verify

log = logging.getLogger(__name__)

COOKIE = "anchorless_admin"
FAILS_PER_MINUTE = 5


def _in(ip: str, nets: list[str]) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.version == 6 and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return any(addr in ipaddress.ip_network(n, strict=False) for n in nets)


class Admin:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._secret: bytes | None = None
        self._fails: dict[str, deque[float]] = defaultdict(deque)

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.admin.password or self.cfg.admin.password_hash)

    def client_ip(self, request: web.Request) -> str:
        """The real client: X-Forwarded-For is believed only from a trusted proxy."""
        ip = request.remote or ""
        trusted = self.cfg.admin.trusted_proxies
        if trusted and _in(ip, trusted):
            hops = [h.strip() for h in request.headers.get("X-Forwarded-For", "").split(",") if h.strip()]
            for hop in reversed(hops):          # the nearest hop that is not one of our proxies
                if not _in(hop, trusted):
                    return hop
        return ip

    def is_https(self, request: web.Request) -> bool:
        if request.secure:
            return True
        trusted = self.cfg.admin.trusted_proxies
        return bool(trusted) and _in(request.remote or "", trusted) and \
            request.headers.get("X-Forwarded-Proto", "").lower() == "https"

    def https_ok(self, request: web.Request, required: bool) -> bool:
        """Fine unless https is required and this is plain http from another machine."""
        return (not required or self.is_https(request)
                or _in(self.client_ip(request), ["127.0.0.0/8", "::1/128"]))

    def _require_https(self, request: web.Request) -> None:
        if not self.https_ok(request, self.cfg.admin.require_https):
            raise web.HTTPForbidden(text='{"error": "https required"}', content_type="application/json")

    def _key(self) -> bytes:
        if self._secret is None:
            path = Path(self.cfg.data.dir) / "admin.key"
            try:
                self._secret = path.read_bytes()
            except FileNotFoundError:
                path.parent.mkdir(parents=True, exist_ok=True)
                self._secret = secrets.token_bytes(32)
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(self._secret)
        return hmac.new(self._secret, self.cfg.admin.secret.encode(), hashlib.sha256).digest()

    def _token(self, expires: int) -> str:
        sig = hmac.new(self._key(), str(expires).encode(), hashlib.sha256).hexdigest()
        return f"{expires}.{sig}"

    def logged_in(self, request: web.Request) -> bool:
        token = request.cookies.get(COOKIE, "")
        exp, _, _sig = token.partition(".")
        if not exp.isdigit() or int(exp) < time.time():
            return False
        return hmac.compare_digest(token, self._token(int(exp)))

    def check(self, request: web.Request, write: bool = False) -> None:
        """Raise the right HTTP error unless this request may use the settings."""
        if not self.enabled:
            raise web.HTTPNotFound(text='{"error": "disabled"}', content_type="application/json")
        if not _in(self.client_ip(request), self.cfg.admin.allow_from):
            raise web.HTTPForbidden(text='{"error": "not from an allowed network"}', content_type="application/json")
        self._require_https(request)
        if not self.logged_in(request):
            raise web.HTTPUnauthorized(text='{"error": "login"}', content_type="application/json")
        if write:
            self.check_write(request)

    def check_write(self, request: web.Request) -> None:
        if request.headers.get("X-Anchorless") != "1":
            raise web.HTTPForbidden(text='{"error": "missing X-Anchorless header"}', content_type="application/json")
        origin = request.headers.get("Origin")
        if origin:
            host = request.headers.get("X-Forwarded-Host") or request.host
            if urlsplit(origin).netloc != host:
                raise web.HTTPForbidden(text='{"error": "cross-site request"}', content_type="application/json")

    # --- handlers ---

    async def login(self, request: web.Request) -> web.Response:
        if not self.enabled:
            raise web.HTTPNotFound(text='{"error": "disabled"}', content_type="application/json")
        ip = self.client_ip(request)
        if not _in(ip, self.cfg.admin.allow_from):
            raise web.HTTPForbidden(text='{"error": "not from an allowed network"}', content_type="application/json")
        self._require_https(request)
        self.check_write(request)
        fails = self._fails[ip]
        while fails and fails[0] < time.monotonic() - 60:
            fails.popleft()
        if len(fails) >= FAILS_PER_MINUTE:
            raise web.HTTPTooManyRequests(text='{"error": "too many tries - wait a minute"}',
                                          content_type="application/json")
        try:
            password = str((await request.json()).get("password", ""))
        except Exception:
            password = ""
        if not await self._password_ok(password):
            fails.append(time.monotonic())
            log.warning("settings: wrong password from %s", ip)
            raise web.HTTPUnauthorized(text='{"error": "wrong password"}', content_type="application/json")
        fails.clear()
        days = self.cfg.admin.session_days
        expires = int(time.time() + days * 86400)
        resp = web.json_response({"ok": True})
        secure = self.is_https(request)
        resp.set_cookie(COOKIE, self._token(expires), max_age=int(days * 86400), httponly=True,
                        samesite="Strict", secure=secure, path="/")
        log.info("settings: login from %s", ip)
        return resp

    async def _password_ok(self, password: str) -> bool:
        a = self.cfg.admin
        if a.password_hash:     # scrypt: ~50 ms of CPU, off the event loop
            return await asyncio.to_thread(verify, password, a.password_hash)
        return hmac.compare_digest(password.encode(), (a.password or "").encode())

    async def logout(self, request: web.Request) -> web.Response:
        resp = web.json_response({"ok": True})
        resp.del_cookie(COOKIE, path="/")
        return resp
