"""Safe outbound fetches for public mode: a hosted server must not become a way into its own network.

Before connecting, and again on every redirect, the host is resolved and every address must be a
public internet address: no private, loopback, link-local, multicast, reserved or cloud-metadata
addresses (169.254.169.254, fd00::/8, ...). Only http/https on ports 80/443, at most 5 redirects
(followed by hand), 5 MB per response, 15 s timeout.

Limitation: the host is resolved here and again by the HTTP client when it connects, so a DNS server
that answers differently the second time (DNS rebinding) isn't stopped by this check alone.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx

MAX_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
TIMEOUT = 15
_BLOCKED = [ipaddress.ip_network(n) for n in (
    "169.254.169.254/32", "100.64.0.0/10", "fd00::/8", "fe80::/10", "::ffff:0:0/96", "64:ff9b::/96")]


class UnsafeURL(ValueError):
    """The URL can't be fetched in public mode; the message says why, in plain words."""


def _resolve(host: str, port: int) -> list[str]:   # tests replace this
    return [info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]


def _public(ip: ipaddress._BaseAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not (ip.is_multicast or ip.is_reserved) and not any(ip in n for n in _BLOCKED)


def check_target(url: str) -> None:
    """Raise UnsafeURL unless url is http(s) on port 80/443 and its host resolves only to public addresses."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UnsafeURL("Only http:// and https:// links can be scanned.")
    if not parts.hostname:
        raise UnsafeURL("That doesn't look like a web address.")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        raise UnsafeURL("That web address has an invalid port.") from None
    if port not in (80, 443):
        raise UnsafeURL("Only standard web ports (80 and 443) can be scanned on the hosted server.")
    try:
        addrs = _resolve(parts.hostname, port)
    except (socket.gaierror, UnicodeError):
        raise UnsafeURL(f"Couldn't find the site {parts.hostname}.") from None
    if not addrs or not all(_public(ipaddress.ip_address(a.split("%")[0])) for a in addrs):
        raise UnsafeURL("That address points to a private or local network, which the hosted server won't scan.")


def client() -> httpx.Client:   # tests replace this to use a mock transport
    return httpx.Client(follow_redirects=False, timeout=TIMEOUT)


def safe_get(http: httpx.Client, url: str, headers: dict | None = None) -> str:
    """GET url, checking the target before connecting and on every redirect; returns the body as text."""
    for _ in range(MAX_REDIRECTS + 1):
        check_target(url)
        with http.stream("GET", url, headers=headers, follow_redirects=False) as r:
            if r.is_redirect and r.headers.get("location"):
                url = urljoin(url, r.headers["location"])
                continue
            body = bytearray()
            for chunk in r.iter_bytes():
                body += chunk
                if len(body) > MAX_BYTES:
                    raise UnsafeURL("That page is larger than 5 MB, the hosted server's limit.")
            return body.decode(r.encoding or "utf-8", errors="replace")
    raise UnsafeURL(f"That link redirects more than {MAX_REDIRECTS} times.")
