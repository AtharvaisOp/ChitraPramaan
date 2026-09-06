"""Bound untrusted public-image fetches and reject private redirect targets.

Deployments should additionally enforce network-level egress restrictions: DNS
validation alone cannot eliminate DNS rebinding between lookup and connection.
"""
import ipaddress
import socket
from urllib.parse import urlsplit, urljoin

import requests


def validate_public_url(url: str) -> None:
    try:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            raise ValueError
        port = parts.port or (443 if parts.scheme == "https" else 80)
        if port not in {80, 443}:
            raise ValueError
        addresses = socket.getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError
    except (ValueError, OSError) as exc:
        raise requests.RequestException("Unsafe or unresolvable public source URL") from exc


def public_request(url: str, *, method: str, timeout: tuple, max_bytes: int = 0):
    """Check every redirect; stream image data within the caller's byte budget."""
    for _ in range(6):
        validate_public_url(url)
        request = requests.head if method == "HEAD" else requests.get
        response = request(url, allow_redirects=False, timeout=timeout, stream=True)
        try:
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location")
                if not location:
                    raise requests.RequestException("Source redirect has no target")
                url = urljoin(url, location)
                continue
            response.raise_for_status()
            if method == "HEAD":
                return response.url or url
            content = bytearray()
            for chunk in response.iter_content(65536):
                if len(content) + len(chunk) > max_bytes:
                    raise requests.RequestException("Source image exceeds byte limit")
                content.extend(chunk)
            return bytes(content)
        finally:
            response.close()
    raise requests.RequestException("Source redirected too many times")
