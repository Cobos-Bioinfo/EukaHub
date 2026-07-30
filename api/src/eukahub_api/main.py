"""EukaHub API — read-only serving of the genomic-resource dataset.

Phase 2 (the API) is landing endpoint by endpoint. Live so far:

- ``GET /clade/{taxid}/summary`` — the Genomic Resource Summary (Q1).

Still to come (see docs/roadmap.md): breakdown, taxon/lineage, export.tsv,
name search. ``/health`` and ``/metrics-config`` remain from the scaffold.
"""

import os

from eukahub_core.metrics import METRICS
from fastapi import FastAPI, HTTPException

from eukahub_api.db import Conn, lifespan
from eukahub_api.queries import TaxonNotFound, fetch_summary
from eukahub_api.schemas import CladeSummary

app = FastAPI(title="EukaHub API", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, object]:
    return {"status": "ok", "database_configured": "DATABASE_URL" in os.environ}


@app.get("/metrics-config")
def metrics_config() -> list[dict[str, str]]:
    """The tracked metrics — static card chrome the frontend renders once,
    keyed by the same metric keys the per-clade payloads use."""
    return [
        {
            "key": m.key,
            "card_title": m.card_title,
            "coverage_column": m.coverage_key,
            "total_column": m.total_key,
        }
        for m in METRICS
    ]


@app.get("/clade/{taxid}/summary", response_model=CladeSummary)
def clade_summary(taxid: int, conn: Conn) -> CladeSummary:
    """Genomic Resource Summary for one taxon: species count + per-resource
    coverage/total/percent. One indexed lookup on `clade_features`."""
    try:
        name, rank, meta = fetch_summary(conn, taxid)
    except TaxonNotFound:
        raise HTTPException(status_code=404, detail=f"taxon {taxid} not found")
    return CladeSummary.from_metadata(name, rank, meta)
