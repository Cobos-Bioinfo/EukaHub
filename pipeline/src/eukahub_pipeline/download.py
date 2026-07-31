"""Download and unpack the NCBI taxdump (nodes.dmp + names.dmp)."""

from __future__ import annotations

import logging
import tarfile
from pathlib import Path

import requests

log = logging.getLogger("eukahub.download")

TAXDUMP_URL = "https://ftp.ncbi.nlm.nih.gov/pub/taxonomy/taxdump.tar.gz"

# Only these two members are needed; the archive holds several others.
_WANTED = ("nodes.dmp", "names.dmp")


def download_taxdump(
    dest_dir: str | Path, url: str = TAXDUMP_URL, force: bool = False
) -> Path:
    """Fetch and extract nodes.dmp + names.dmp into ``dest_dir``.

    Skips the download when both files are already present unless ``force``.
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    if not force and all((dest / m).exists() for m in _WANTED):
        log.info("taxdump already present in %s; skipping download", dest)
        return dest

    tgz = dest / "taxdump.tar.gz"
    log.info("Downloading %s -> %s", url, tgz)
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(tgz, "wb") as fh:
            fh.writelines(r.iter_content(chunk_size=1 << 20))

    log.info("Extracting %s", ", ".join(_WANTED))
    with tarfile.open(tgz) as tar:
        for member in _WANTED:  # fixed names — no path-traversal risk
            tar.extract(member, dest)

    tgz.unlink(missing_ok=True)
    return dest
