"""``/health`` (liveness) and ``/health/ready`` (database readiness)."""

import logging

from fastapi import APIRouter, Request, Response

log = logging.getLogger("eukahub.api")

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness: the process is up and serving. Checks no dependencies, so a
    container/orchestrator can tell 'process alive' apart from 'DB ready'."""
    return {"status": "ok"}


@router.get("/health/ready")
def readiness(request: Request, response: Response) -> dict[str, str]:
    """Readiness: can we actually serve reads? Pings Postgres with SELECT 1 and
    returns 503 if it's unreachable, so a load balancer holds traffic until the
    read-only serving DB is back."""
    try:
        with request.app.state.pool.connection() as conn:
            conn.execute("SELECT 1")
    # Any failure — DB down, pool timeout, unexpected error — means "not ready".
    except Exception:
        log.warning("readiness check failed", exc_info=True)
        response.status_code = 503
        return {"status": "unavailable", "database": "unreachable"}
    return {"status": "ready", "database": "ok"}
