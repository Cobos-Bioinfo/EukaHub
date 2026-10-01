"""Where the build downloads its inputs from, and how long each request may take.

Each value can be overridden through an environment variable; rebuild.yml fills
them from GitHub Actions repository variables. An unset or empty variable keeps
the default. The NCBI datasets CLI is fetched by rebuild.yml itself.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from eukahub_core.config import check_https_url, check_seconds


@dataclass(frozen=True, slots=True)
class Source:
    url: str
    timeout: float  # seconds per request


@dataclass(frozen=True, slots=True)
class Sources:
    taxdump: Source
    ena: Source
    annotrieve: Source


TAXDUMP = Source("https://ftp.ncbi.nlm.nih.gov/pub/taxonomy/taxdump.tar.gz", 120)
ENA = Source("https://www.ebi.ac.uk/ena/portal/api", 300)
ANNOTRIEVE = Source("https://genome.crg.es/annotrieve/api/v0", 600)

# (field, URL variable, timeout variable, default)
_VARIABLES = (
    ("taxdump", "TAXDUMP_URL", "TAXDUMP_TIMEOUT_SECONDS", TAXDUMP),
    ("ena", "ENA_PORTAL_URL", "ENA_TIMEOUT_SECONDS", ENA),
    ("annotrieve", "ANNOTRIEVE_API_URL", "ANNOTRIEVE_TIMEOUT_SECONDS", ANNOTRIEVE),
)


def load_sources(environ: Mapping[str, str]) -> Sources:
    """The sources configured in ``environ``. Raises ``ValueError`` naming the
    variable when a value is invalid, so a misconfigured rebuild stops before
    downloading anything and publishes nothing."""
    resolved = {}
    for field, url_var, timeout_var, default in _VARIABLES:
        url = environ.get(url_var, "").strip()
        timeout = environ.get(timeout_var, "").strip()
        try:
            url = check_https_url(url) if url else default.url
        except ValueError as e:
            raise ValueError(f"{url_var} {e}") from None
        try:
            seconds = check_seconds(timeout) if timeout else default.timeout
        except ValueError as e:
            raise ValueError(f"{timeout_var} {e}") from None
        resolved[field] = Source(url.rstrip("/"), seconds)
    return Sources(**resolved)
