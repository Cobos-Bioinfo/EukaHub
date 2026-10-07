"""Every resource of the API, mapped onto one router.

- ``GET /health``, ``/health/ready``  liveness and database readiness.
- ``GET /config``                     what a client reads once: dataset stamp, measure
  chrome, deployment links and groups.
- ``GET /taxons``                     taxa by name, parent, rank under a taxon or taxid,
  with their counts; sorted, filtered and paged.
- ``GET /taxons/stats``               the quality stats of the same taxa, page for page.
- ``GET /taxons/report``              every taxon the same list would page through, as TSV.
- ``GET /taxons/aggregates``          data for a set of clades (include minus exclude).
- ``GET /taxons/{taxid}``             one taxon, the same object ``/taxons`` lists.
- ``GET /taxons/{taxid}/ancestors``   the root down to the taxon, as taxa.
- ``GET /taxons/{taxid}/stats``       the quality stats of one taxon.
- ``GET /assemblies``                 genome assemblies, optionally under a taxon.
- ``GET /annotations``                gene annotations, optionally under a taxon.

Lists page with an opaque cursor (see ``pagination``). Every error is problem
details (see ``errors``).
"""

from fastapi import APIRouter

from eukahub_api import errors
from eukahub_api.resources import annotations, assemblies, config, health, taxons

router = APIRouter(responses=errors.RESPONSES)

router.include_router(health.router, tags=["health"])
router.include_router(config.router, tags=["config"])
router.include_router(taxons.router, tags=["taxons"])
router.include_router(assemblies.router, tags=["assemblies"])
router.include_router(annotations.router, tags=["annotations"])
