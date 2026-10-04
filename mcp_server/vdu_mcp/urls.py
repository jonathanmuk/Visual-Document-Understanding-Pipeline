"""Rules for fetching a document from a URL.

A URL given to read_document usually comes from a language model, and a model
can be steered by text it has read (prompt injection). Without rules, such a URL
could make this server fetch something only it can reach: the Redis service, the
cloud's metadata endpoint, an internal admin page. So before every connection:

    only https, unless VDU_FETCH_ALLOW_HTTP is on;
    the host name is looked up, and every address it has must be public
    (not private, loopback, link-local, or reserved);
    if VDU_FETCH_ALLOWED_HOSTS is set, the host must be on that list;
    redirects are followed one hop at a time, at most three, each checked again.

VDU_FETCH_URLS=off turns URL sources off entirely; local paths still work.

What remains: the address is checked, then the HTTP client looks the name up
again when it connects. A DNS server that answers differently the second time
(DNS rebinding) could slip past. The MCP pod's NetworkPolicy blocks traffic to
private address ranges, which closes that gap at the network level.
"""
import asyncio
import ipaddress
import os
import socket
import urllib.parse
from typing import Awaitable, Callable

MAX_REDIRECTS = 3

Resolver = Callable[[str, int], Awaitable[list[str]]]


class UrlNotAllowed(Exception):
    pass


def _flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "on", "yes")


async def system_resolver(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({info[4][0] for info in infos})


class FetchPolicy:
    def __init__(self, enabled: bool | None = None, allow_http: bool | None = None,
                 allowed_hosts: list[str] | None = None, allow_private: bool | None = None,
                 resolver: Resolver | None = None):
        self.enabled = _flag("VDU_FETCH_URLS", True) if enabled is None else enabled
        self.allow_http = _flag("VDU_FETCH_ALLOW_HTTP", False) if allow_http is None else allow_http
        if allowed_hosts is None:
            allowed_hosts = [h.strip().lower() for h in os.getenv("VDU_FETCH_ALLOWED_HOSTS", "").split(",") if h.strip()]
        self.allowed_hosts = allowed_hosts
        # Only for local testing against a file server on your own machine.
        self.allow_private = _flag("VDU_FETCH_ALLOW_PRIVATE", False) if allow_private is None else allow_private
        self.resolver = resolver or system_resolver


def is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def host_listed(host: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if pattern.startswith("*."):
            if host.endswith(pattern[1:]):
                return True
        elif host == pattern:
            return True
    return False


async def check(url: str, policy: FetchPolicy) -> None:
    """Raise UrlNotAllowed unless this URL may be fetched."""
    if not policy.enabled:
        raise UrlNotAllowed("fetching documents from URLs is turned off on this server; use a local file path")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or (parts.scheme == "http" and not policy.allow_http):
        raise UrlNotAllowed(f"only https URLs are accepted (got {parts.scheme or 'no scheme'})")
    host = (parts.hostname or "").lower()
    if not host:
        raise UrlNotAllowed("the URL has no host")
    if policy.allowed_hosts and not host_listed(host, policy.allowed_hosts):
        raise UrlNotAllowed(f"{host} is not in this server's list of allowed hosts")
    if policy.allow_private:
        return
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        raise UrlNotAllowed("the URL has an invalid port")
    try:
        addresses = await policy.resolver(host, port)
    except OSError:
        raise UrlNotAllowed(f"could not look up {host}")
    if not addresses:
        raise UrlNotAllowed(f"could not look up {host}")
    for address in addresses:
        if not is_public(address):
            raise UrlNotAllowed(f"{host} points to {address}, which is not a public address, so it is not fetched")
