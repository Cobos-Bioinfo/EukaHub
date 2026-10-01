"""Checks for deployment settings read from the environment."""

import math
from urllib.parse import urlsplit


def check_https_url(value: str, *, placeholder: str | None = None) -> str:
    """Return ``value`` if it is an absolute https URL (containing ``placeholder``
    when one is given), else raise ``ValueError``."""
    if any(c.isspace() or not c.isprintable() for c in value):
        raise ValueError("contains whitespace or control characters")
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("must be an https:// URL with a host")
    if placeholder is not None and placeholder not in value:
        raise ValueError(f"must contain {placeholder}")
    return value


def check_seconds(value: str, *, maximum: float | None = None) -> float:
    """Parse a positive number of seconds (at most ``maximum``), else raise
    ``ValueError``."""
    try:
        seconds = float(value)
    except ValueError:
        seconds = math.nan
    if not 0 < seconds < math.inf or (maximum is not None and seconds > maximum):
        bound = f" and at most {maximum:g}" if maximum is not None else ""
        raise ValueError(f"must be a number of seconds above 0{bound}")
    return seconds
