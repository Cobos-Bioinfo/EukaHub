# Architecture

## Goals that shape the design

- **Production-solid, not a toy.** This is a portfolio piece and a real tool,
  potentially deployed and maintained by CRG / guigolab (who host Annotrieve,
  one of our data sources). "Looks and behaves like a real product."
- **A learning vehicle.** Deliberately built on mainstream, in-demand
  technologies rather than the path of least resistance.
- **Read-only serving of a periodically-rebuilt dataset.** See
  [`data-model.md`](data-model.md) for why this single fact simplifies almost
  everything.

## The deployment host reality (CRG / guigolab)

Since guigolab may host this, their stack is a real input. What Annotrieve and
the wider org use:

| Layer | guigolab / Annotrieve | Notes for us |
|---|---|---|
| Backend | Python | Aligns with keeping our Python domain logic + pipeline. |
| Database | **MongoDB** | Competes with Postgres purely on host-alignment; both fit our workload (see data-model). |
| Frontend | **Vue + TypeScript** | Competes with React on host-alignment vs. broadest market. |
| API | REST + OpenAPI spec | **FastAPI auto-generates OpenAPI** — clean match. |
| Packaging | Docker + docker-compose | We adopt this regardless. It is how they deploy and it is good practice. |
| Pipelines | Nextflow (in several repos) | Optional future alignment for our build pipeline. |

Takeaway: **backend (Python/FastAPI), REST+OpenAPI, and Docker are settled and
aligned.** The database-engine and frontend-framework forks have now been
resolved in favour of the broadest-showcase options — **PostgreSQL** and
**React + TypeScript** — with Docker keeping the guigolab deploy path open
regardless of their Mongo/Vue defaults. See [`../DECISIONS.md`](../DECISIONS.md).

## Target architecture (reference shape)

Three deployable pieces plus a database, all containerized:

```
  ┌────────────────────────┐        ┌──────────────────────────┐
  │  Frontend (SPA)        │  HTTP  │  API service (FastAPI)   │
  │  React + TypeScript    │ ─────► │  Python                  │
  │  - Dashboard (Q1)      │  REST  │  - /clade/{taxid}/summary│
  │  - Breakdown (Q2)      │ ◄───── │  - /clade/{taxid}/breakdown
  │  - (later) ToL view    │  JSON  │  - /taxon/{taxid} (lineage)
  └────────────────────────┘        │  - /export.tsv           │
                                     └────────────┬─────────────┘
                                                  │ read-only
                                                  ▼
                                     ┌──────────────────────────┐
                                     │  Database (Postgres/Mongo)│
                                     │  taxonomy + clade rollups │
                                     └──────────────────────────┘
            ▲ rebuilt on a schedule (offline, not in the request path)
  ┌─────────┴───────────────────────────────────────────────────┐
  │  Build pipeline (Python; DuckDB/Polars for the rollup)       │
  │  taxdump + NCBI + Annotrieve + ENA  →  load DB               │
  └──────────────────────────────────────────────────────────────┘
```

Because everything is read-only, the API is cache-friendly and the common-clade
responses can even be pre-generated. We get Streamlit's "just serves fast"
property back without its constraints.

## Why FastAPI (settled)

- Reuses the strongest existing assets: the Python domain logic
  (`database.py`, the filter/sort/limit, the `Metric` config) and the whole
  build pipeline port almost verbatim. Rewriting the domain layer in TypeScript
  would throw that away and reintroduce the SQL/Python drift bug class the old
  project worked hard to kill.
- Auto-generated OpenAPI matches guigolab's `annotrieve-api-specs.yaml`
  convention and gives typed clients and free interactive docs.
- Async, fast, and the mainstream Python API framework today.

## Frontend shape (React + TypeScript)

The UI is not large: the dashboard (four metric cards + total-species + a
Wikipedia "About" card + a breadcrumb) and one filter/sort/limit **breakdown
view** (table with coverage bars, optionally a bar chart). It is a comfortable
and instructive first real SPA.

The **eventual interactive Tree of Life** is the reason to pick a serious
frontend now rather than a minimal one. That is a WebGL/canvas rendering problem
(cf. OneZoom, Lifemap), and React's ecosystem for it is deep (deck.gl,
react-three-fiber, visx, D3). The DB already supports it: `parent_id` gives
cheap lazy-expand-on-click, and the materialized lineage gives bulk-subtree
fetches (see data-model). Meta-framework (Next.js vs Vite) is deferred to
scaffold time — see [`../DECISIONS.md`](../DECISIONS.md).

## Build pipeline (mostly kept)

Keep it in Python. Changes:

- **Taxonomy from NCBI taxdump directly** (`nodes.dmp`, `names.dmp`) instead of
  ETE3. Compute `parent_id` + materialized path at build time.
- **Rollup with DuckDB/Polars** instead of the dict-accumulation loop (optional
  but recommended; it is the natural columnar use).
- **Target the live DB** (load Postgres/Mongo) instead of shipping a 400 MB
  SQLite file for the app to download.
- Keep the resumable-snapshot and atomic-swap discipline. Consider Nextflow
  later if deeper guigolab alignment is wanted.
