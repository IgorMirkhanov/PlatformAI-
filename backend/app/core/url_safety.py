"""SSRF-safe URL validation for knowledge-base crawls and CRM webhooks."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "metadata.google.internal",
        "metadata",
    }
)


def _assert_host_not_private(raw: str, *, allowed_schemes: set[str]) -> str:
    parsed = urlparse(raw)
    if parsed.scheme not in allowed_schemes:
        schemes = ", ".join(sorted(allowed_schemes))
        raise ValueError(f"Only {schemes} URLs are allowed.")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise ValueError("URL host is required.")
    if host in _BLOCKED_HOSTNAMES or host.endswith(".localhost") or host.endswith(".local"):
        raise ValueError("URL host is not allowed.")
    if host == "0.0.0.0":
        raise ValueError("URL host is not allowed.")

    # Literal IP in the URL
    try:
        ip = ipaddress.ip_address(host)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ValueError("Private or reserved IP addresses are not allowed.")
        return raw
    except ValueError as exc:
        if "not allowed" in str(exc).lower() or "private" in str(exc).lower():
            raise
        # host is a hostname — resolve DNS
        pass

    try:
        infos = socket.getaddrinfo(host, parsed.port or None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"Unable to resolve host '{host}'.") from exc

    if not infos:
        raise ValueError(f"Unable to resolve host '{host}'.")

    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        addr = sockaddr[0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ValueError("URL resolves to a private or reserved address.")

    return raw


def assert_safe_public_http_url(url: str) -> str:
    """
    Validate that ``url`` is http(s) and does not resolve to a private/link-local host.

    Raises ``ValueError`` on SSRF-risky targets. Returns the normalized URL string.
    """
    raw = (url or "").strip()
    if not raw:
        raise ValueError("URL is required.")
    if not raw.startswith(("http://", "https://")):
        raw = f"https://{raw}"
    return _assert_host_not_private(raw, allowed_schemes={"http", "https"})


def assert_safe_public_https_url(url: str) -> str:
    """
    Stricter SSRF guard for CRM automation webhooks: ``https://`` only,
    no private/loopback/link-local targets.
    """
    raw = (url or "").strip()
    if not raw:
        raise ValueError("URL is required.")
    if not raw.startswith("https://"):
        raise ValueError("Only https URLs are allowed.")
    return _assert_host_not_private(raw, allowed_schemes={"https"})
