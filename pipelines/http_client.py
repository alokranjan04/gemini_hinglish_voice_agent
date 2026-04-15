# -*- coding: utf-8 -*-
"""
Shared persistent aiohttp ClientSession.
Import get_http() wherever you need to make outbound HTTP requests so the
connection pool is reused across calls rather than recreated per-request.
"""
import aiohttp

_SESSION: aiohttp.ClientSession | None = None


def get_http() -> aiohttp.ClientSession:
    global _SESSION
    if _SESSION is None or _SESSION.closed:
        _SESSION = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=20, ttl_dns_cache=300)
        )
    return _SESSION
