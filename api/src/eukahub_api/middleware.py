"""What every response goes through: security and cache headers, ETags, and one
log line per request."""

import hashlib
import logging
import os
import time

from fastapi import Request, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger("eukahub.api")

# Baseline security headers on every API response (defense-in-depth; nginx sets
# its own on the static SPA it serves). HSTS/CSP belong with the TLS terminator.
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}

# The dataset is read-only and rebuilt offline, so a GET response is valid until
# the next rebuild — safe to cache downstream (browser / CDN / reverse proxy).
# Tune CACHE_MAX_AGE (seconds) to the rebuild cadence; health stays uncached.
_CACHE_MAX_AGE = int(os.environ.get("CACHE_MAX_AGE", "3600"))


def _etag_of(body: bytes) -> str:
    """A weak ETag over the exact response bytes. md5 is a content fingerprint
    here (not a security primitive); weak so downstream transforms (gzip) don't
    invalidate the match, which is the semantics we want for a whole-body tag."""
    return f'W/"{hashlib.md5(body, usedforsecurity=False).hexdigest()}"'


def _if_none_match(header: str | None, etag: str) -> bool:
    """RFC 7232 If-None-Match test (weak comparison): ``*`` matches anything,
    otherwise the client's list must contain our tag, ignoring the ``W/`` prefix."""
    if not header:
        return False
    if header.strip() == "*":
        return True
    norm = etag.removeprefix("W/").strip()
    return any(t.strip().removeprefix("W/").strip() == norm for t in header.split(","))


async def add_response_headers(request: Request, call_next):
    """Baseline security headers on every response, plus Cache-Control and an
    ETag on cacheable GETs (setdefault so a handler that set its own keeps
    precedence). A matching If-None-Match short-circuits to a bodyless 304."""
    response = await call_next(request)
    for header, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    # Caching applies to GET (the routes are GET-only — a HEAD gets 405, which is
    # never cached, so `curl -I` shows a reverse-proxy MISS; test the cache with a
    # real GET).
    if request.method != "GET":
        return response
    # Health must stay fresh; other successful GETs are cacheable until rebuild.
    if request.url.path.startswith("/health"):
        response.headers.setdefault("Cache-Control", "no-store")
        return response
    if response.status_code != 200:
        return response
    response.headers.setdefault("Cache-Control", f"public, max-age={_CACHE_MAX_AGE}")
    # ETag + conditional requests for materialized JSON. The middleware runs over
    # a streaming wrapper (BaseHTTPMiddleware), so buffer the body to fingerprint
    # it — cheap for these small JSON payloads. The streamed TSV export
    # (text/tab-separated-values) is left untouched. A revalidating client that
    # already holds this exact body gets a bodyless 304.
    if not response.headers.get("content-type", "").startswith("application/json"):
        return response
    body = b"".join([chunk async for chunk in response.body_iterator])
    etag = _etag_of(body)
    response.headers.setdefault("ETag", etag)
    headers = dict(response.headers)
    headers.pop("content-length", None)  # recomputed from the body / empty 304
    if _if_none_match(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    return Response(content=body, status_code=response.status_code, headers=headers)


class HeadAsGet:
    """Answers HEAD as GET without the body: every general-purpose HTTP server
    supports HEAD (RFC 9110), while FastAPI routes only the methods declared."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "HEAD":
            await self.app(scope, receive, send)
            return

        async def send_headers_only(message: Message) -> None:
            if message["type"] != "http.response.body":
                await send(message)
            elif not message.get("more_body", False):
                await send({"type": "http.response.body", "body": b""})

        await self.app({**scope, "method": "GET"}, receive, send_headers_only)


async def log_requests(request: Request, call_next):
    """One structured log line per request. Health probes drop to DEBUG so they
    don't flood the log at the default INFO level."""
    start = time.perf_counter()
    response = await call_next(request)
    level = logging.DEBUG if request.url.path.startswith("/health") else logging.INFO
    log.log(
        level,
        "request",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round((time.perf_counter() - start) * 1000, 1),
        },
    )
    return response
