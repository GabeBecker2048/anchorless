"""Keep feed fetching on the public internet.

The server, not the browser, fetches feed URLs. Inside a home network that
server can reach things nobody outside can - a router's admin page, other
services without a login - so a feed URL typed into the settings page could
point it at them (server-side request forgery). Every feed request, including
each redirect, is checked here: the host name is resolved and the request is
refused if any address it resolves to is private, loopback, link-local,
carrier-grade NAT (Tailscale), multicast or reserved.

[feeds] allow_private = true switches this off, for a feed hosted on your own
network. It is file-only: the settings page cannot change it.

Not covered: a DNS answer that changes between this check and the connection
(DNS rebinding). Closing that would mean connecting to the checked address
ourselves; this check stops the plain cases, which are the ones that matter on
a LAN-only settings page behind a password.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

import httpx

_CGNAT = ipaddress.ip_network("100.64.0.0/10")      # carrier-grade NAT; Tailscale addresses


class BlockedURL(ValueError):
    pass


def is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT:
        return False
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
                or ip.is_reserved or ip.is_unspecified)


async def check_url(url: str, allow_private: bool = False) -> None:
    """Raise BlockedURL unless ``url`` is http(s) to a public address (or private ones are allowed)."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise BlockedURL("a feed URL must start with http:// or https://")
    host = parts.hostname
    if not host:
        raise BlockedURL("a feed URL needs a host name")
    if allow_private:
        return
    try:
        addrs = [ipaddress.ip_address(host)]
    except ValueError:
        port = parts.port or (443 if parts.scheme == "https" else 80)
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as err:
            raise BlockedURL(f"cannot resolve {host}: {err.strerror or err}") from err
        addrs = [ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos]
    blocked = [str(a) for a in addrs if not is_public(a)]
    if blocked:
        raise BlockedURL(f"{host} is on a private network ({blocked[0]}); feeds must be on the "
                         "public internet ([feeds] allow_private = true in the file allows it)")


def guard_hooks(allow_private: bool) -> dict:
    """httpx event hooks that check every request, redirects included."""
    async def check(request: httpx.Request) -> None:
        await check_url(str(request.url), allow_private)
    return {"request": [check]}
