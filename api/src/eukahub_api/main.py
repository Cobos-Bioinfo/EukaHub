"""EukaHub API — Phase 0 placeholder.

Real endpoints (summary, breakdown, taxon/lineage, export.tsv, name search)
arrive in Phase 2. For now this wires the container to the shared core so the
scaffold is verifiably end-to-end: a health check and an echo of the metric
config (the single source of truth).
"""

import os

from fastapi import FastAPI

from eukahub_core.metrics import METRICS

app = FastAPI(title="EukaHub API", version="0.1.0")

# Set by docker-compose; read here so the wiring is visible even though the
# read paths don't exist yet.
DATABASE_URL = os.environ.get("DATABASE_URL")


@app.get("/health")
def health() -> dict[str, object]:
    return {"status": "ok", "database_configured": DATABASE_URL is not None}


@app.get("/metrics-config")
def metrics_config() -> list[dict[str, str]]:
    """Echo the tracked metrics — placeholder until the real read endpoints
    land in Phase 2."""
    return [
        {
            "key": m.key,
            "card_title": m.card_title,
            "coverage_column": m.coverage_key,
            "total_column": m.total_key,
        }
        for m in METRICS
    ]
