# Migration roadmap

Staged so there is a working, demoable thing at the end of each phase, and so
the two open decisions (DB engine, frontend framework) only need to be locked
before the phases that depend on them.

## Phase 0 — Decide & scaffold
- Resolve the two open forks in [`../DECISIONS.md`](../DECISIONS.md)
  (DB engine, frontend framework).
- Repo layout (monorepo suggested): `pipeline/`, `api/`, `web/`,
  `infra/` (docker-compose), `docs/`.
- `docker-compose.yml` with the chosen DB + a placeholder API + web.

## Phase 1 — Data foundation (the real work)
- Load NCBI **taxdump** into the `taxon` table/collection: `taxid, name, rank,
  parent_id, path`. Verify counts against the old DB (~1.8M eukaryote nodes).
- Port the **rollup** into `clade_features` (reuse Euka-Survey's logic; move the
  aggregation to DuckDB/Polars). Validate against the old
  `precomputed_clade_features` numbers for known clades (e.g. Eukaryota 2759).
- Confirm the two canonical queries run fast **without** `precomputed_taxa` and
  **without** ETE3. This phase proves the whole thesis of the redesign.

## Phase 2 — API
- FastAPI endpoints: `summary`, `breakdown` (filter/sort/limit pushed down),
  `taxon`/lineage (breadcrumb), `export.tsv`, name search.
- Port the `Metric` config as the single source of truth; generate OpenAPI +
  TypeScript types from it.
- Response caching for common clades.

## Phase 3 — Frontend: the dashboard (Q1)
- Rebuild the "Genomic Resource Summary": four metric cards, total-species,
  coverage bars, Wikipedia "About" card, lineage breadcrumb, root picker.
- This is the piece you already like; get it looking sharp first.

## Phase 4 — Frontend: the breakdown (Q2)
- The filter/sort/limit **table** with coverage bars (the old Table tab,
  reborn as a real component), plus a coverage bar chart.
- Downloads (displayed rows + full breakdown TSV).

## Phase 5 — Productionization
- Dockerized deploy, health checks, structured logging (fixes the old
  logging-gap), scheduled rebuild (GitHub Actions or Nextflow), a staging vs
  prod DB, basic metrics.

## Phase 6 — Stretch: interactive Tree of Life
- WebGL/canvas hierarchical view with lazy-expand (uses `parent_id`) and
  subtree fetch (uses the materialized lineage). The ambitious showcase piece.

## What we reuse from Euka-Survey vs rebuild

| Reuse (port) | Rebuild | Delete |
|---|---|---|
| Build pipeline (Python) | Presentation (Streamlit → SPA) | ETE3 (build + runtime) |
| Rollup/aggregation logic | Data-access as an HTTP API | PyQt5 / matplotlib tree |
| `Metric` config | Taxonomy storage (into our DB) | `precomputed_taxa` + index |
| filter/sort/limit semantics | | 400 MB download model |
| Schema-version discipline | | |
| Wikipedia "About" card idea | | |
