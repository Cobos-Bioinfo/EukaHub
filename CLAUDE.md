# CLAUDE.md — EukaHub

Resume anchor for a fresh session. Read this, then the docs below.

## What this is

A production-grade rewrite of **Euka-Survey** (a Streamlit app exploring public
genomic-data availability across the tree of life). The old app lives intact at
`../Euka-Survey` (sibling dir) — read it when porting logic.

For any user-picked taxon the app answers two questions:
1. **How much data is there?** (the "Genomic Resource Summary" dashboard)
2. **How is it distributed at a lower rank?** (breakdown: table/chart now,
   interactive Tree of Life later)

Data sources: NCBI (assemblies), Annotrieve (annotations), ENA (RNA-Seq). The
dataset is rebuilt offline on a schedule and served **read-only** — this drives
most of the design.

## Status

**Phases 0–1 complete & validated** (2026-07-29). uv workspace (`core`/`api`/
`pipeline`), `web/` Vite placeholder, `infra/docker-compose.yml` (Postgres +
`ltree`). Phase 1 loaded the taxdump into `taxon` (2.9M nodes, `ltree` paths)
and rolled leaf features up into `clade_features` (1.83M clades) with Polars —
no ETE3, no `precomputed_taxa`. Matches Euka-Survey within 0.3%; summary lookup
and worst-case (Eukaryota→phylum) breakdown both run in <1 ms server-side.

**Phase 2 (the API) — all five read endpoints done** (2026-07-30):
`summary` (Q1), `breakdown` (Q2 — descendants at a rank via one `ltree`
subtree query, filter/sort/limit pushed into SQL, `COUNT(*) OVER ()` for the
pre-limit total), `export.tsv` (full breakdown streamed via a server-side
cursor; old public TSV schema), `taxon/{taxid}` (root→node lineage via
`path @>` + `nlevel`), and `search` (name search, `pg_trgm` GIN index on
`taxon.name` — added to the schema and the live DB). Structure: pooled
`psycopg` (`api/…/db.py`), SQL in `queries.py`, Pydantic responses +
query-param enums both derived from `METRICS`. Breakdown defaults mirror
Euka-Survey (sort `n_rows`, exclude-empty, AND, top 25; ranks =
ALLOWED_RANKS). 36 end-to-end tests vs the live DB (shared `client` fixture
in `api/tests/conftest.py`).

**Phase 3 (the dashboard) — Q1 done** (2026-07-30). Typed API bridge:
`export_openapi.py` dumps `app.openapi()` → `web/src/api/openapi.json`;
`openapi-typescript` generates `schema.ts`; `openapi-fetch` client in
`client.ts` (`npm run gen` regenerates both). The React SPA renders the
Genomic Resource Summary for `/clade/:taxid` — metric cards + coverage meters
(`/metrics-config` joined to `summary`), total species, lineage breadcrumb
(`/taxon/{id}`), and a name-search root picker (`/search`). Verified via
typecheck + vite build + the Vite `/api` proxy against a live API; user
manually confirmed Q1 in a browser (2026-07-31).

**Phase 4 (the breakdown, Q2) — table done** (2026-07-31). `BreakdownSection`
renders below the Q1 cards on `/clade/:taxid` (keyed by taxid so a new root
resets controls): rank + sort + limit selects, per-resource filter chips with
an AND/OR toggle, an exclude-empty switch, and a comparison table of child taxa
with per-metric coverage meters. Sort/filter labels now come from the metric
config too — added `filter_label`/`sort_count_label`/`sort_total_label` to the
API's `MetricConfig` and regenerated the TS types, so control copy can't drift.
Two downloads: displayed rows (client-side TSV from the loaded items) and the
full breakdown (`/clade/{taxid}/export.tsv`).

**Phase 4 complete — divergent bar chart added** (2026-07-31). A Table/Chart
toggle in `BreakdownSection` drives both views from the same controls/data.
`DivergentBarChart` ports Euka-Survey's overlaid mirror bar: per taxon, left
half = assemblies+annotations (blue), right half = RNA-Seq+long-read (green),
each side's darker subset metric overlaid on its lighter base; the plotted
value is coverage % (0–100 per side). Built in HTML/CSS (no chart lib) with a
recessive gridline track, a dashed centre axis, a legend, and a per-row hover
tooltip. Exposed `side`/`overlay`/`legend_label` on the API's `MetricConfig`
(same no-drift path as the labels). Followed the **dataviz** skill: the 4 fixed
entity colors PASS CVD + normal-vision separation; the pale-hue lightness/
contrast FAILs are handled by relief (grey track + inset bar edge) + the table
view, per the validator's guidance — kept the palette rather than recolor.
Verified via typecheck + vite build + full API suite (31 passed) + curl;
**not yet screenshotted** (no headless browser), and the app is light-only so
chart dark mode is deferred with the rest. See `docs/roadmap.md`.

**Phase 5 (productionization) — in progress on `dev`** (2026-07-31). Two slices
done. (1) Observability: structured JSON logging (`logging_config.py`, `LOG_LEVEL`
env) + a per-request middleware; `/health` = liveness, `/health/ready` = DB
readiness (`SELECT 1`, 503 when unreachable); 33 API tests. (2) Dockerized
deploy: `web/Dockerfile.prod` (multi-stage — `node:22-slim` build →
`nginx:alpine` serving the built SPA and proxying `/api`) + `web/nginx.conf`;
`infra/docker-compose.prod.yml` (project `eukahub-prod`, own volume, container
healthchecks, **only web published on 8080** — Postgres + API stay internal).
User-verified end-to-end: full stack builds, all three containers healthy,
nginx→api→db path works. Secrets already externalized (DECISIONS 2026-07-31).
**Next: CORS + security headers, then scheduled rebuild + CI, then response
caching** — full checklist (incl. remaining security items) in `docs/roadmap.md`.

Run the build (Postgres up): `uv run --package eukahub-pipeline python -m
eukahub_pipeline.build` (add `--skip-download` to reuse an unpacked taxdump).
Run the API: `uv run --package eukahub-api uvicorn eukahub_api.main:app`.
Run the web app (dev, proxies `/api` → API): `cd web && npm install && npm run
dev`. Regenerate TS types after API changes: `cd web && npm run gen`.
Tests (whole workspace, DB up): `uv run pytest`.
Prod smoke test (full stack in containers, web on `:8080`; needs `sudo` here):
`docker compose -f infra/docker-compose.prod.yml up --build -d` · tear down with
`... down -v`.

## Read before doing anything

- `docs/data-model.md` — **the core doc.** DB design + taxonomy-tree storage.
- `docs/architecture.md` — target stack and how it maps to the deploy host.
- `docs/roadmap.md` — the staged plan.
- `DECISIONS.md` — every settled decision and the few still open.
- `README.md` — overview + status.

## Settled stack (why in DECISIONS.md)

- **DB:** PostgreSQL. Taxonomy = `parent_id` (adjacency) + `ltree` lineage.
  Feature rollups kept from Euka-Survey.
- **Backend:** FastAPI (Python), REST + auto-OpenAPI. Reuse old domain logic.
- **Frontend:** React + TypeScript (Vite + React Router SPA).
- **Packaging:** Docker + docker-compose. Python deps via **uv** (workspace).
- **Pipeline:** Python; taxonomy from NCBI taxdump; assemblies via the NCBI
  `datasets` CLI (installed in the dev env); rollup via DuckDB/Polars.

## Non-negotiables (don't reintroduce the old pain)

- **No ETE3** (build or runtime). Taxonomy lives in Postgres.
- **No `precomputed_taxa`-style cache.** The breakdown is one indexed `ltree`
  query for any root.
- **Serving is read-only;** rebuilt offline. Denormalize freely.

## Immediate next step (Phase 5 — continue productionization)

Phases 0–4 are done. **Phase 5 is underway on `dev`** (see Status): structured
logging + health checks and the Dockerized deploy are shipped. Remaining, in
order: **CORS + security headers** (API-side, testable solo — the assistant owns
this; see the Phase 5 security checklist), then the **scheduled offline rebuild
+ CI** (GitHub Actions; keep the atomic-swap discipline) and **staging-vs-prod
DB**, then **response caching** for common clades. Remaining security items
(no public `5432` — done in prod compose; TLS, rate limiting, the read-only-API
auth decision) are enumerated in `docs/roadmap.md` Phase 5 and must be actioned
as reached. (Phase 6 is the stretch interactive Tree of Life — the DB already
supports it via `parent_id` lazy-expand + materialized lineage.)

Smaller follow-ups worth doing along the way:
- **Screenshot/verify Q1 + Q2 in a browser** — the dev env has no headless
  browser, so the UI is build- and curl-verified only (user eyeballed Q1; Q2
  table + chart still need a human look).
- **Response caching** for common clades (Eukaryota, Metazoa, …) — read-only
  between rebuilds, so it's cache-friendly.
- **App-wide dark mode** — currently light-only; the chart defers to that.

## Still open

Nothing — all forks resolved. Rollup engine settled on **Polars** at Phase 1
(DuckDB remains a viable alternative). See DECISIONS.md.
