# Architecture

## What shapes the design

- **Production-solid, not a toy.** A portfolio piece and a real tool, potentially
  deployed by CRG / guigolab (who host Annotrieve, one of our data sources).
- **A learning vehicle** — mainstream, in-demand technologies over the path of
  least resistance.
- **Read-only serving of a periodically-rebuilt dataset.** See
  [`data-model.md`](data-model.md) for why this simplifies almost everything.

## Deploy host (CRG / guigolab)

guigolab may host this, so their stack is a real input:

| Layer | guigolab / Annotrieve | Our choice |
|---|---|---|
| Backend | Python | FastAPI (aligned) |
| Database | MongoDB | **PostgreSQL** (both fit; see data-model) |
| Frontend | Vue + TypeScript | **React + TypeScript** (broadest market) |
| API | REST + OpenAPI | FastAPI auto-generates OpenAPI (aligned) |
| Packaging | Docker + docker-compose | adopted as-is |
| Pipelines | Nextflow | optional future alignment |

Backend, REST+OpenAPI, and Docker are aligned with the host. The DB and frontend
forks went to the broadest-showcase options; Docker keeps the guigolab deploy
path open regardless. See [`../DECISIONS.md`](../DECISIONS.md).

## Target shape

Three containerized pieces plus a database:

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
                                     │  Database (PostgreSQL)   │
                                     │  taxonomy + clade rollups │
                                     └──────────────────────────┘
            ▲ rebuilt on a schedule (offline, not in the request path)
  ┌─────────┴───────────────────────────────────────────────────┐
  │  Build pipeline (Python; DuckDB/Polars for the rollup)       │
  │  taxdump + NCBI + Annotrieve + ENA  →  load DB               │
  └──────────────────────────────────────────────────────────────┘
```

Because everything is read-only, the API is cache-friendly and common-clade
responses can be pre-generated.

## Frontend note

The UI is small: the dashboard (metric cards + total-species + a Wikipedia
"About" card + breadcrumb) and one filter/sort/limit breakdown view. The reason
to pick a serious frontend now is the **eventual interactive Tree of Life** — a
WebGL/canvas problem where React's ecosystem is deep (deck.gl, react-three-fiber,
visx, D3). The DB already supports it: `parent_id` gives lazy-expand-on-click,
the materialized lineage gives bulk-subtree fetches.

Shipped as a **Vite + React Router SPA** (no SSR need yet — see
[`../DECISIONS.md`](../DECISIONS.md)).

## Build pipeline (mostly kept from Euka-Survey)

Stays in Python. Changes:

- **Taxonomy from NCBI taxdump** (`nodes.dmp`, `names.dmp`) instead of ETE3;
  compute `parent_id` + materialized path at build time.
- **Assemblies via the NCBI `datasets` CLI** (installed in the dev
  environment) — the `get_assemblies` fetch step ports mostly as-is.
- **Rollup with DuckDB/Polars** instead of the dict-accumulation loop.
  (Pandas is deliberately excluded — see `../DECISIONS.md`.)
- **Target the live DB** (load Postgres) instead of shipping a 400 MB SQLite file.
- Keep the resumable-snapshot and atomic-swap discipline. Consider Nextflow later
  for deeper guigolab alignment.
