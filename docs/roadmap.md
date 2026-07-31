# Migration roadmap

Staged so there is a working, demoable thing at the end of each phase. The two
open forks (DB engine, frontend framework) only need locking before the phases
that depend on them.

## Phase 0 — Decide & scaffold
- Resolve the open forks in [`../DECISIONS.md`](../DECISIONS.md).
- Monorepo layout: `pipeline/`, `api/`, `web/`, `infra/` (docker-compose), `docs/`.
- `docker-compose.yml` with Postgres + a placeholder API + web.

## Phase 1 — Data foundation (the real work)
- Load NCBI **taxdump** into `taxon`: `taxid, name, rank, parent_id, path`.
  Verify counts against the old DB (~1.8M eukaryote nodes).
- Port the **rollup** into `clade_features` (reuse Euka-Survey's logic; move the
  aggregation to DuckDB/Polars). Validate against the old numbers for known
  clades (e.g. Eukaryota 2759).
- Confirm both canonical queries run fast **without** `precomputed_taxa` and
  **without** ETE3. This proves the thesis of the redesign.

## Phase 2 — API
- FastAPI endpoints: `summary`, `breakdown` (filter/sort/limit pushed down),
  `taxon`/lineage (breadcrumb), `export.tsv`, name search.
- Port the `Metric` config as single source of truth; generate OpenAPI + TS types
  from it. Response caching for common clades.

## Phase 3 — Frontend: the dashboard (Q1)
- Rebuild the "Genomic Resource Summary": metric cards, total-species, coverage
  bars, Wikipedia "About" card, lineage breadcrumb, root picker.

## Phase 4 — Frontend: the breakdown (Q2)
- The filter/sort/limit **table** with coverage bars, plus a bar chart.
- Downloads (displayed rows + full breakdown TSV).

## Phase 5 — Productionization

### Deploy & runtime
- **[done]** Full Dockerized deploy: `web/Dockerfile.prod` (multi-stage —
  `node:22-slim` build → `nginx:alpine` serving the SPA + proxying `/api`) and
  `infra/docker-compose.prod.yml` (all three services containerized, container
  healthchecks, only web published). User-verified end-to-end.
- **[done]** Health checks (`/health` liveness, `/health/ready` DB) + structured
  JSON logging (`logging_config.py`, per-request middleware).
- Scheduled offline rebuild (GitHub Actions or Nextflow) keeping the
  resumable-snapshot + atomic-swap discipline; staging vs prod DB; basic metrics.
- Response caching for common clades (Eukaryota, Metazoa, …) — read-only between
  rebuilds, so cache-friendly.

### Security & secrets — assistant owns this; acknowledge & fix each when reached
Credential externalization is **done** (compose reads `${POSTGRES_*:-eukahub}`,
`infra/.env.example` committed, `infra/.env` gitignored). Remaining, to action
in this phase:
- **[done] Postgres `5432` not published in prod.** `infra/docker-compose.prod.yml`
  keeps Postgres (and the API) on the internal network — only web is published
  (8080). The `5432:5432` mapping remains a local-dev convenience in the dev
  compose only.
- **Real prod credentials from a secret store** (GitHub Actions secrets / host
  env), never committed. Gotcha: Postgres applies `POSTGRES_PASSWORD` only on
  first volume init — a real password needs a fresh volume or `ALTER USER`.
- **TLS/HTTPS** terminated at a gateway / reverse proxy in front of `api` + `web`.
- **[done] CORS** — configurable allowlist via `CORS_ALLOW_ORIGINS` (FastAPI
  CORSMiddleware, GET-only, no credentials). **Rate limiting** at the gateway
  still to add.
- **Auth decision:** the API serves public, read-only data — confirm no user auth
  is needed (vs. optional API keys purely for abuse control) and record it.
- **[done] Security headers**: baseline (`X-Content-Type-Options`,
  `X-Frame-Options`, `Referrer-Policy`) on API responses (middleware) and on the
  static SPA (`web/nginx.conf`, in `location /` so `/api` isn't double-set).
  **HSTS + a CSP** still to add with TLS. Plus a **dependency / secret scan** in
  CI (still to add).

### Verify
- `docker compose config` resolves; a fresh clone comes up on dev defaults with
  no committed secret; prod overrides via `--env-file`.

## Phase 6 — Stretch: interactive Tree of Life
- WebGL/canvas hierarchical view with lazy-expand (`parent_id`) and subtree fetch
  (materialized lineage). The ambitious showcase piece.

## Reuse vs rebuild vs delete

| Reuse (port) | Rebuild | Delete |
|---|---|---|
| Build pipeline (Python) | Presentation (Streamlit → SPA) | ETE3 (build + runtime) |
| Rollup/aggregation logic | Data-access as an HTTP API | PyQt5 / matplotlib tree |
| `Metric` config | Taxonomy storage (into our DB) | `precomputed_taxa` + index |
| filter/sort/limit semantics | | 400 MB download model |
| Schema-version discipline | | |
| Wikipedia "About" card idea | | |
