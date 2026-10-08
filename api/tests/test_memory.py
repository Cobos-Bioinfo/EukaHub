"""Memory of the API under every query, on a dataset far larger than the real one.

Each test sends one request to a real API process (uvicorn) serving a synthetic
dataset and fails if the process's peak resident memory goes over 256 MB while
answering it. The peak is reset before each request (``/proc/<pid>/clear_refs``),
so every query is measured on its own. Downloads are read as a stream and thrown
away, so the client never holds them.

The dataset: Eukaryota with 50 phyla, each level ten times wider down to families,
then 4 genera per family and 9 species per genus, about 2.1 million taxa (the real
taxonomy has about 1 million); 2,000,000 assemblies and 1,000,000 annotations
spread over the species (28 and 50 times the real counts). The counts in
``clade_features`` follow the tree's shape and every taxon has a row of
``clade_stats``; both only need to be plausible.

Slow (the dataset takes about 1.5 minutes to build the first time, and 2 GB of
disk), so these run only when asked for: ``uv run pytest -m ram``. CI runs them.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import psycopg
import pytest
from eukahub_api.db import database_url
from eukahub_api.pagination import encode

pytestmark = [
    pytest.mark.ram,
    pytest.mark.skipif(not Path("/proc/self/clear_refs").exists(), reason="needs Linux /proc"),
]

LIMIT_MB = 256
DATABASE = "eukahub_huge"
SCHEMA = Path(__file__).resolve().parents[2] / "infra" / "postgres" / "init" / "001_schema.sql"

# (rank, first taxid, count, children per parent, species below each)
LEVELS = (
    ("phylum", 10_000_001, 50, 50, 36_000),
    ("class", 11_000_001, 500, 10, 3_600),
    ("order", 12_000_001, 5_000, 10, 360),
    ("family", 13_000_001, 50_000, 10, 36),
    ("genus", 14_000_001, 200_000, 4, 9),
    ("species", 20_000_001, 1_800_000, 9, 1),
)
ASSEMBLIES = 2_000_000
ANNOTATIONS = 1_000_000
SPECIES_FIRST, SPECIES = LEVELS[-1][1], LEVELS[-1][2]


def build(conninfo: str) -> None:
    """Create the schema in an empty database and fill it."""
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute(SCHEMA.read_text())
        conn.execute(
            "INSERT INTO taxon VALUES (1, 'root', 'no rank', 1, '1'), "
            "(131567, 'cellular organisms', 'cellular root', 1, '1.131567'), "
            "(2759, 'Eukaryota', 'domain', 131567, '1.131567.2759')"
        )
        parent_first, parent_count = 2759, 1
        for rank, first, count, per_parent, _species in LEVELS:
            conn.execute(
                "INSERT INTO taxon (taxid, name, rank, parent_id, path) "
                "SELECT c, initcap(%(rank)s) || ' ' || c, %(rank)s, p.taxid, "
                "p.path || c::text "
                "FROM generate_series(%(first)s, %(first)s + %(count)s - 1) c "
                "JOIN taxon p ON p.taxid = CASE WHEN %(pcount)s = 1 THEN %(pfirst)s "
                "  ELSE %(pfirst)s + (c - %(first)s) / %(per)s END",
                {
                    "rank": rank,
                    "first": first,
                    "count": count,
                    "pfirst": parent_first,
                    "pcount": parent_count,
                    "per": per_parent,
                },
            )
            parent_first, parent_count = first, count
        species_below = " ".join(
            f"WHEN t.rank = '{rank}' THEN {n}" for rank, _f, _c, _p, n in LEVELS
        )
        conn.execute(
            "INSERT INTO clade_features "
            "SELECT taxid, n, n / 3, n / 5, n / 4, n / 20, n, n / 2, n * 40, n, "
            "n / 20, n / 4, n / 3, n / 3, n / 10 "
            f"FROM (SELECT t.taxid, CASE {species_below} ELSE {SPECIES} END AS n FROM taxon t) x"
        )
        conn.execute(
            "INSERT INTO clade_stats "
            "SELECT taxid, 90 + taxid % 10, 15000 + taxid % 5000, "
            "1e8 + taxid % 1000000, 1e6 + taxid % 100000 FROM taxon"
        )
        conn.execute(
            "INSERT INTO assembly SELECT "
            "'GCA_' || lpad(i::text, 9, '0') || '.1', "
            f"{SPECIES_FIRST} + (i * 7919) % {SPECIES}, "
            "(ARRAY['Complete Genome','Chromosome','Scaffold','Contig'])[1 + i % 4], "
            "CASE WHEN i % 7 = 0 THEN NULL ELSE (i * 104729) % 90000000 END, "
            "(i * 15485863) % 900000000, (i * 32452843) % 3000000000, 30 + i % 40, "
            "CASE WHEN i % 50 = 0 THEN 'representative genome' END, "
            "DATE '2000-01-01' + (i % 9000)::int, 'Submitter ' || i % 5000, "
            "(ARRAY['GenBank','RefSeq'])[1 + i % 2], ARRAY['PRJNA' || i % 100000], "
            "'https://www.ncbi.nlm.nih.gov/datasets/genome/GCA_' || lpad(i::text, 9, '0') || '.1/' "
            f"FROM generate_series(1::bigint, {ASSEMBLIES}) i"
        )
        conn.execute(
            "INSERT INTO annotation SELECT "
            "md5(i::text), 'GCA_' || lpad(i::text, 9, '0') || '.1', "
            f"{SPECIES_FIRST} + (i * 7919) % {SPECIES}, "
            "(ARRAY['Ensembl','NCBI','community'])[1 + i % 3], 'provider', "
            "DATE '2005-01-01' + (i % 7000)::int, 'https://example.org/' || i || '.gff3.gz', "
            "10000 + i % 30000, CASE WHEN i % 9 = 0 THEN NULL ELSE 8000 + i % 20000 END, "
            "CASE WHEN i % 5 = 0 THEN NULL ELSE 50 + (i % 500) / 10.0 END, 80, 2, "
            "'eukaryota_odb12' "
            f"FROM generate_series(1::bigint, {ANNOTATIONS}) i"
        )
        conn.execute(
            "INSERT INTO dataset_meta (built_at, taxon_count, assembly_count, annotation_count, "
            "clade_count) SELECT now(), (SELECT count(*) FROM taxon), "
            f"{ASSEMBLIES}, {ANNOTATIONS}, (SELECT count(*) FROM clade_features)"
        )
        conn.execute("ANALYZE")


SPECIES = SPECIES_FIRST
PHYLUM = LEVELS[0][1]


def _url_for(dbname: str) -> str:
    parts = urllib.parse.urlsplit(database_url())
    return urllib.parse.urlunsplit(parts._replace(path=f"/{dbname}"))


def _fingerprint() -> str:
    """Changes whenever the schema or ``build`` does, so a stale dataset is rebuilt."""
    return hashlib.sha256((SCHEMA.read_text() + inspect.getsource(build)).encode()).hexdigest()


@pytest.fixture(scope="module")
def huge_database() -> str:
    """The synthetic dataset's connection URL, built once and kept between runs.
    The database's comment holds the fingerprint of the schema and builder it was
    made with, written after the build, so it also marks a complete build."""
    url = _url_for(DATABASE)
    try:
        with psycopg.connect(url) as conn:
            (comment,) = conn.execute(
                "SELECT shobj_description(oid, 'pg_database') FROM pg_database "
                "WHERE datname = current_database()"
            ).fetchone()
        if comment == _fingerprint():
            return url
    except psycopg.Error:
        pass
    try:
        with psycopg.connect(_url_for("postgres"), autocommit=True) as conn:
            conn.execute(f"DROP DATABASE IF EXISTS {DATABASE}")
            conn.execute(f"CREATE DATABASE {DATABASE}")
    except psycopg.OperationalError:
        pytest.skip("serving Postgres not reachable")
    build(url)
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(f"COMMENT ON DATABASE {DATABASE} IS '{_fingerprint()}'")
    return url


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def api(huge_database: str):
    """``(base URL, pid)`` of an API process serving the synthetic dataset, with a
    statement timeout long enough for every query to finish."""
    port = _free_port()
    env = {
        **os.environ,
        "DATABASE_URL": huge_database,
        "API_ROOT_PATH": "",
        "DB_STATEMENT_TIMEOUT_MS": "600000",
        "LOG_LEVEL": "WARNING",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "eukahub_api.main:app", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            urllib.request.urlopen(f"{base}/health/ready", timeout=2)
            break
        except OSError:
            time.sleep(0.5)
    else:
        proc.kill()
        pytest.fail("the API did not start")
    yield base, proc.pid
    proc.terminate()
    proc.wait(timeout=10)


def _peak_mb(pid: int) -> float:
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith("VmHWM:"):
            return int(line.split()[1]) / 1024
    raise AssertionError("no VmHWM in /proc status")


def _cursor(ordering: str, *values: object) -> str:
    return encode(list(values), ordering=ordering, backward=False)


# One request per query, at the largest page each endpoint allows.
REQUESTS = {
    "config": "/config",
    "taxon": f"/taxons/{SPECIES}",
    "ancestors": f"/taxons/{SPECIES}/ancestors",
    "every species, first page": "/taxons?within=2759&rank=species&limit=1000",
    "every species, deep page": "/taxons?within=2759&rank=species&limit=1000&cursor="
    + _cursor("species:desc", 1, 0, "Species 20900000", 20900000),
    "children of a big node": "/taxons?parent=2759&limit=1000",
    "search matching 1.8M names": "/taxons?q=pecies&limit=50",
    "close spellings": "/taxons?q=Specis%2020000001&fuzzy=true&limit=50",
    "gaps of every genus": "/taxons?within=2759&rank=genus&sort_by=resources.assemblies.missing&limit=1000",
    "100 chosen taxa": "/taxons?taxids="
    + ",".join(str(SPECIES + i) for i in range(100))
    + "&limit=100",
    "stats of the root": "/taxons/2759/stats",
    "stats of 50 phyla": "/taxons/stats?within=2759&rank=phylum&limit=50",
    "stats of 1000 genera": "/taxons/stats?within=2759&rank=genus&limit=1000",
    "set of clades": f"/taxons/aggregates?include=2759&exclude={PHYLUM}",
    "report of every species": "/taxons/report?within=2759&rank=species",
    "assemblies, first page": "/assemblies?within=2759&limit=200",
    "assemblies, deep page": "/assemblies?within=2759&limit=200&cursor="
    + _cursor("assembly:release_date:desc", False, "2001-01-01", "GCA_000000000.1"),
    "annotations by BUSCO": "/annotations?within=2759&limit=200",
}


@pytest.mark.parametrize("path", REQUESTS.values(), ids=REQUESTS.keys())
def test_query_stays_under_the_memory_limit(api, path):
    base, pid = api
    Path(f"/proc/{pid}/clear_refs").write_text("5")  # reset the peak to the current RSS
    start = time.perf_counter()
    received = 0
    try:
        with urllib.request.urlopen(base + path, timeout=900) as response:
            status = response.status
            while chunk := response.read(1 << 16):
                received += len(chunk)
    except urllib.error.HTTPError as e:
        pytest.fail(f"{e.code}: {json.loads(e.read()).get('detail')}")
    peak = _peak_mb(pid)
    seconds = time.perf_counter() - start
    print(f"{path[:70]:70} {status} {received / 1e6:8.1f} MB sent {seconds:6.1f} s peak {peak:5.0f} MB")
    assert peak < LIMIT_MB, f"the API peaked at {peak:.0f} MB"
