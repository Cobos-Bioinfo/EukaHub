"""Wikipedia summary lookup for a taxon's "About" card.

A single lightweight GET against Wikipedia's REST summary endpoint, which
returns a short JSON (one-line description + first-paragraph extract +
thumbnail URL) and transparently follows redirects — so NCBI scientific names
like "Metazoa" or "Viridiplantae" resolve to the right article without us
maintaining a name map.

Why this lives server-side (an API proxy, not a browser fetch): Wikipedia's
API policy wants a descriptive ``User-Agent`` — a header browsers forbid
``fetch`` from setting — and doing the call here lets us cache it across
viewers and keep the external egress off the client. There's no SSRF surface:
the URL is fixed to the summary endpoint with the (URL-encoded) name.

Results are cached per name for 24h (mirroring Euka-Survey), so there's at most
one request per unique root taxon per TTL — and we cache the *absence* of an
article too, so taxa without a Wikipedia page don't re-hit the network. The
lookup is decorative and never load-bearing: any failure (network, non-200,
disambiguation, no extract) yields ``None`` and the caller omits the card.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
import urllib.request

from eukahub_api.schemas import TaxonAbout

log = logging.getLogger("eukahub.api.wikipedia")

_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
_TIMEOUT_SECONDS = 6
_CACHE_TTL_SECONDS = 86_400  # 24h; Wikipedia content changes slowly
# Wikipedia's API policy requires a descriptive User-Agent; requests without
# one can be rejected with HTTP 403.
_USER_AGENT = "EukaHub/1.0 (https://github.com/Cobos-Bioinfo/EukaHub)"

# Names we never resolve — placeholders that would only ever miss.
_UNRESOLVABLE = {"", "Unknown", "Error"}

# Module-level TTL cache: name -> (expiry_epoch, result). A lock keeps the
# read-modify-write consistent across FastAPI's sync-handler threadpool; a rare
# race would only cost a duplicate fetch, so this is cheap insurance.
_cache: dict[str, tuple[float, TaxonAbout | None]] = {}
_cache_lock = threading.Lock()


def fetch_about(name: str) -> TaxonAbout | None:
    """Return the Wikipedia summary for ``name``, or ``None`` if there's no
    usable article. Cached per name for 24h (including the ``None`` result)."""
    if name in _UNRESOLVABLE:
        return None

    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(name)
        if cached is not None and cached[0] > now:
            return cached[1]

    result = _lookup(name)

    with _cache_lock:
        _cache[name] = (now + _CACHE_TTL_SECONDS, result)
    return result


def _lookup(name: str) -> TaxonAbout | None:
    """Perform the (uncached) Wikipedia REST summary request for ``name``."""
    url = _SUMMARY_URL.format(title=urllib.parse.quote(name))
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as resp:
            if resp.status != 200:
                return None
            data = json.load(resp)
    # Any failure — network, timeout, non-200 (HTTPError), bad JSON — is a miss.
    except (OSError, ValueError) as e:
        log.info("Wikipedia summary lookup failed for %r: %s", name, e)
        return None

    # Skip disambiguation pages and entries with no real summary text.
    if data.get("type") == "disambiguation" or not data.get("extract"):
        return None

    content_urls = data.get("content_urls") or {}
    desktop = content_urls.get("desktop") or {}
    return TaxonAbout(
        title=data.get("title") or name,
        description=data.get("description") or "",
        extract=data.get("extract") or "",
        thumbnail=(data.get("thumbnail") or {}).get("source"),
        url=desktop.get("page")
        or f"https://en.wikipedia.org/wiki/{urllib.parse.quote(name)}",
    )
