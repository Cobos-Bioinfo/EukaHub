"""Keep the serving database up to date with the latest published dataset.

Runs as a long-lived sidecar next to the API. Once a day it asks GitHub for the
latest dataset Release and, if that Release is newer than what is loaded,
downloads it and hands it to ``restore_snapshot``, which stages and verifies the
new data before swapping it in.

This is what makes the deployment hands-off. Two jobs, not one:

  * **Initial load.** A freshly started stack has an empty database. The first
    cycle notices there is no dataset and loads the current Release, so bringing
    the stack up is the whole install: no manual restore, no seed step.
  * **Monthly refresh.** ``rebuild.yml`` publishes a new Release; the next cycle
    picks it up on its own.

Everything is a plain unauthenticated HTTPS GET against a public Release, so
there is no token to store, expire, or rotate, and nothing needs to reach *in*
to the server. A Release is used rather than a workflow artifact because
artifacts are deleted after 90 days: a server that sat idle, or three failed
rebuilds in a row, would otherwise find nothing to download.

Failure is always safe. A bad or unreachable Release, a failed download, or a
snapshot that does not pass the invariant checks all leave the running dataset
exactly as it was; the cycle is logged and retried later. The site keeps serving
the data it already has, which may go stale but never goes wrong.

    EUKAHUB_REPO=owner/name REFRESH_INTERVAL=86400 python scripts/auto_refresh.py
    python scripts/auto_refresh.py --once    # one cycle, then exit
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path

import psycopg

# Sits beside this file; running "python scripts/auto_refresh.py" puts the
# script's own directory on sys.path, so the plain import resolves.
import restore_snapshot

log = logging.getLogger("auto-refresh")

DEFAULT_REPO = "Cobos-Bioinfo/EukaHub"
ASSET_NAME = "eukahub-dataset.dump"
# Tags are dataset-YYYYMMDD; the date is what decides whether a Release is newer
# than the loaded dataset, so it is parsed rather than string-compared.
TAG_PATTERN = re.compile(r"^dataset-(\d{4})(\d{2})(\d{2})$")
DEFAULT_INTERVAL = 86_400  # once a day; new data appears monthly
RETRY_INTERVAL = 3_600  # after a failed cycle, try again sooner


def _latest_release(repo: str) -> tuple[date, str]:
    """Return the newest Release's dataset date and the snapshot's download URL."""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    # A token is not needed for a public repo, but is honoured when present so
    # the same image works against a private one.
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)

    tag = payload.get("tag_name", "")
    match = TAG_PATTERN.match(tag)
    if not match:
        raise RuntimeError(f"latest release tag {tag!r} is not dataset-YYYYMMDD")
    released = date(int(match[1]), int(match[2]), int(match[3]))

    for asset in payload.get("assets", []):
        if asset.get("name") == ASSET_NAME:
            return released, asset["browser_download_url"]
    raise RuntimeError(f"release {tag} has no {ASSET_NAME} asset")


def _loaded_dataset_date(url: str) -> date | None:
    """The build date of the dataset currently serving, or None if there is none.

    None covers every "this database holds no usable dataset" case: the server
    is not up yet, the database is empty, the schema has never been applied, or
    a build was interrupted before it stamped dataset_meta. All of them mean the
    same thing to the caller, which is: load the current Release.
    """
    try:
        with psycopg.connect(url, connect_timeout=10) as conn:
            row = conn.execute("SELECT built_at FROM dataset_meta").fetchone()
    except psycopg.Error as exc:
        log.warning("could not read dataset_meta (%s)", type(exc).__name__)
        return None
    if not row or row[0] is None:
        return None
    built_at = row[0]
    return built_at.date() if isinstance(built_at, datetime) else built_at


def refresh_once(database_url: str, repo: str) -> bool:
    """Load the latest Release if it is newer than what is serving.

    Returns True when a new dataset was promoted.
    """
    released, download_url = _latest_release(repo)
    loaded = _loaded_dataset_date(database_url)

    if loaded is None:
        log.info("no dataset loaded; installing release dataset-%s", released.isoformat())
    elif released > loaded:
        log.info("release dataset-%s is newer than loaded %s", released, loaded)
    else:
        log.info("up to date (loaded %s, latest release %s)", loaded, released)
        return False

    restore_snapshot.restore(
        database_url,
        restore_snapshot._download(download_url, Path("/tmp") / ASSET_NAME),
    )
    log.info("now serving dataset-%s", released.isoformat())
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

    while True:
        try:
            refresh_once(database_url, repo)
            wait = interval
        except (urllib.error.URLError, OSError, RuntimeError, psycopg.Error) as exc:
            # Never let a bad cycle kill the loop: the running dataset is
            # untouched, so the only cost is staying on it a little longer.
            log.error("refresh cycle failed (%s: %s)", type(exc).__name__, exc)
            wait = RETRY_INTERVAL
        if args.once:
            return
        log.info("next check in %d minutes", wait // 60)
        time.sleep(wait)


if __name__ == "__main__":
    main()
