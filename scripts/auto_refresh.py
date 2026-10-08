"""Keep the serving database on the latest published dataset Release.

Long-lived sidecar. Each cycle first finishes any interrupted swap, then reads the
newest ``dataset-YYYYMMDD`` Release of ``EUKAHUB_REPO`` that carries a dump; unless
the live database was installed from that very Release (same tag and dump), it
downloads the snapshot and hands it to ``restore_snapshot.restore``, which stages,
verifies, records and swaps it in. The live dataset is never touched by a failed
cycle, a Release that keeps failing is skipped until a newer one appears, and a
Release someone rolled back from is not installed again.

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

# Sibling module: running "python scripts/auto_refresh.py" puts scripts/ on sys.path.
import restore_snapshot
from restore_snapshot import ReleaseId

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

    @property
    def id(self) -> ReleaseId:
        return ReleaseId(self.tag, self.sha256)


def _dataset_release(payload: dict) -> Release | None:
    """``payload`` as a dataset Release, or None for any other Release (a code
    release, a draft, a pre-release) or one without the dump."""
    tag = payload.get("tag_name", "")
    match = TAG_PATTERN.match(tag)
    if not match or payload.get("draft") or payload.get("prerelease"):
        return None
    for asset in payload.get("assets", []):
        if asset.get("name") == ASSET_NAME:
            digest = asset.get("digest") or ""
            return Release(
                tag,
                date(int(match[1]), int(match[2]), int(match[3])),
                asset["browser_download_url"],
                asset.get("size"),
                digest.removeprefix("sha256:") if digest.startswith("sha256:") else None,
            )
    return None


def _newest_release(repo: str) -> Release:
    """The newest dataset Release of ``repo`` that carries the dump, whichever Release
    GitHub marks as latest."""
    url = f"https://api.github.com/repos/{repo}/releases?per_page=100"
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    releases = [r for r in map(_dataset_release, payload) if r is not None]
    if not releases:
        raise RuntimeError(f"{repo} has no dataset-YYYYMMDD Release with {ASSET_NAME}")
    return max(releases, key=lambda r: r.tag)


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


def refresh_once(
    database_url: str, repo: str, failures: Counter[ReleaseId] | None = None
) -> bool:
    """Install the newest dataset Release unless it is the one serving.

    ``failures`` counts failed installs per Release across cycles; one that reached
    ``MAX_INSTALL_ATTEMPTS`` is skipped until it is republished or a newer one
    appears. Returns True when a dataset was promoted.
    """
    failures = Counter() if failures is None else failures
    restore_snapshot.repair(database_url)
    release = _newest_release(repo)
    installed = restore_snapshot.installed_release(database_url)
    current = installed.release if installed else None

    if installed and installed.skip and release.id.same_as(installed.skip):
        log.info("not installing %s: it was rolled back; waiting for a newer Release", release.tag)
        return False
    if release.id.same_as(current):
        age = (datetime.now(UTC).date() - release.released).days
        if age > STALE_AFTER_DAYS:
            log.warning(
                "dataset is %d days old and no newer release exists; check that the "
                "rebuild workflow in %s is still enabled and succeeding",
                age,
                repo,
            )
        else:
            log.info("up to date (%s)", release.tag)
        return False
    if current is not None and current.tag > release.tag:
        log.info("serving %s, newer than any published Release; not downgrading", current.tag)
        return False

    if failures[release.id] >= MAX_INSTALL_ATTEMPTS:
        log.warning(
            "skipping %s: it failed to install %d times; waiting for a newer release",
            release.tag,
            failures[release.id],
        )
        return False

    serving = current.tag if current else "nothing recorded"
    log.info("installing %s (serving: %s)", release.tag, serving)
    with tempfile.TemporaryDirectory() as tmp:
        dump = restore_snapshot.download(release.download_url, Path(tmp) / ASSET_NAME)
        try:
            _verify_download(dump, release)
            restore_snapshot.restore(database_url, dump, release=release.id)
        except Exception:
            failures[release.id] += 1
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
    failures: Counter[ReleaseId] = Counter()

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
