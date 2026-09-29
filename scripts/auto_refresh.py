"""Keep the serving database on the latest published dataset Release.

Long-lived sidecar. Each cycle reads the newest ``dataset-YYYYMMDD`` Release of
``EUKAHUB_REPO``; if nothing is loaded yet, or the Release is newer than the loaded
dataset, it downloads the snapshot and hands it to ``restore_snapshot.restore``,
which stages, verifies and swaps it in. The live dataset is never touched by a
failed cycle, and a Release that keeps failing is skipped until a newer one appears.

    EUKAHUB_REPO=owner/name REFRESH_INTERVAL=86400 python scripts/auto_refresh.py
    python scripts/auto_refresh.py --once    # one cycle, then exit
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import tempfile
import time
import urllib.request
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import NamedTuple

import psycopg

# Sibling module: running "python scripts/auto_refresh.py" puts scripts/ on sys.path.
import restore_snapshot

log = logging.getLogger("auto-refresh")

DEFAULT_REPO = "Cobos-Bioinfo/EukaHub"
ASSET_NAME = "eukahub-dataset.dump"
TAG_PATTERN = re.compile(r"^dataset-(\d{4})(\d{2})(\d{2})$")
DEFAULT_INTERVAL = 86_400
RETRY_INTERVAL = 3_600
MAX_INSTALL_ATTEMPTS = 3
STALE_AFTER_DAYS = 45


class Release(NamedTuple):
    tag: str
    released: date
    download_url: str
    size: int | None = None
    sha256: str | None = None


def _latest_release(repo: str) -> Release:
    """The newest Release of ``repo``; raises RuntimeError if it is not a dataset Release."""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)

    tag = payload.get("tag_name", "")
    match = TAG_PATTERN.match(tag)
    if not match:
        raise RuntimeError(f"latest release tag {tag!r} is not dataset-YYYYMMDD")
    released = date(int(match[1]), int(match[2]), int(match[3]))

    for asset in payload.get("assets", []):
        if asset.get("name") == ASSET_NAME:
            digest = asset.get("digest") or ""
            return Release(
                tag,
                released,
                asset["browser_download_url"],
                asset.get("size"),
                digest.removeprefix("sha256:") if digest.startswith("sha256:") else None,
            )
    raise RuntimeError(f"release {tag} has no {ASSET_NAME} asset")


def _verify_download(path: Path, release: Release) -> None:
    """Check a downloaded snapshot against the size and SHA-256 GitHub reports for it.

    Catches truncated or corrupted downloads before they reach pg_restore. A Release
    without a published digest is checked by size alone.
    """
    if release.size is not None and (size := path.stat().st_size) != release.size:
        raise RuntimeError(f"{release.tag}: downloaded {size} bytes, expected {release.size}")
    if release.sha256 is None:
        log.warning("%s has no published digest; skipping the checksum", release.tag)
        return
    sha256 = hashlib.sha256()
    with path.open("rb") as dump:
        while chunk := dump.read(1 << 20):
            sha256.update(chunk)
    if sha256.hexdigest() != release.sha256:
        raise RuntimeError(f"{release.tag}: checksum does not match the published digest")


def _loaded_dataset_date(url: str) -> date | None:
    """UTC build date of the serving dataset, or None when there is no usable one
    (server down, empty database, no schema, or an unstamped build)."""
    try:
        with psycopg.connect(url, connect_timeout=10) as conn:
            row = conn.execute("SELECT built_at FROM dataset_meta").fetchone()
    except psycopg.Error as exc:
        log.warning("could not read dataset_meta (%s)", type(exc).__name__)
        return None
    if not row or row[0] is None:
        return None
    built_at = row[0]
    if isinstance(built_at, datetime):
        return built_at.astimezone(UTC).date() if built_at.tzinfo else built_at.date()
    return built_at


def refresh_once(database_url: str, repo: str, failures: Counter[str] | None = None) -> bool:
    """Install the latest Release if it is newer than what is serving.

    ``failures`` counts failed installs per tag across cycles; a tag that reached
    ``MAX_INSTALL_ATTEMPTS`` is skipped. Returns True when a dataset was promoted.
    """
    failures = Counter() if failures is None else failures
    release = _latest_release(repo)
    loaded = _loaded_dataset_date(database_url)

    if loaded is not None and release.released <= loaded:
        age = (datetime.now(UTC).date() - loaded).days
        if age > STALE_AFTER_DAYS:
            log.warning(
                "dataset is %d days old and no newer release exists; check that the "
                "rebuild workflow in %s is still enabled and succeeding",
                age,
                repo,
            )
        else:
            log.info("up to date (loaded %s, latest release %s)", loaded, release.released)
        return False

    if failures[release.tag] >= MAX_INSTALL_ATTEMPTS:
        log.warning(
            "skipping %s: it failed to install %d times; waiting for a newer release",
            release.tag,
            failures[release.tag],
        )
        return False

    log.info("installing %s (loaded: %s)", release.tag, loaded or "nothing")
    with tempfile.TemporaryDirectory() as tmp:
        dump = restore_snapshot.download(release.download_url, Path(tmp) / ASSET_NAME)
        try:
            _verify_download(dump, release)
            restore_snapshot.restore(database_url, dump)
        except Exception:
            failures[release.tag] += 1
            raise
    log.info("now serving %s", release.tag)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true", help="run a single cycle and exit")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    )
    database_url = os.environ.get("DATABASE_URL", restore_snapshot.DEFAULT_URL)
    repo = os.environ.get("EUKAHUB_REPO", DEFAULT_REPO)
    interval = int(os.environ.get("REFRESH_INTERVAL", DEFAULT_INTERVAL))
    failures: Counter[str] = Counter()

    while True:
        try:
            refresh_once(database_url, repo, failures)
            wait = interval
        except Exception:
            # The live dataset is untouched by a failed cycle; log and try again later.
            log.exception("refresh cycle failed")
            wait = RETRY_INTERVAL
        if args.once:
            return
        log.info("next check in %d minutes", wait // 60)
        time.sleep(wait)


if __name__ == "__main__":
    main()
