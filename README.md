<div align="center">

# EukaHub

**How much of the eukaryotic tree of life has been sequenced, and where are the gaps?**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
&nbsp;![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white)
&nbsp;![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
&nbsp;![React](https://img.shields.io/badge/React-20232A?logo=react&logoColor=61DAFB)
&nbsp;![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white)
&nbsp;![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?logo=postgresql&logoColor=white)

</div>

---

EukaHub is a web app for exploring how much public genomic data exists across the
eukaryotic tree of life. Pick any taxon and it answers two questions:

1. **How much data is there?** Genome assemblies, functional annotations, and
   RNA-Seq (short and long read) for the clade, with assembly-quality and
   annotation-quality statistics (BUSCO completeness, contig N50, genome size,
   gene counts). This is the "Genomic Resource Summary" dashboard.
2. **How is it distributed below that taxon?** Break any clade down at a lower
   rank and compare its subgroups: as an interactive "data map", a radial Tree
   of Life, or a side-by-side comparison, so the under-sequenced groups stand
   out at a glance.

The dataset is rebuilt offline on a schedule and served **read-only**, which
shapes most of the design: reads are fast aggregate lookups over a precomputed
rollup, and the whole thing runs comfortably on a single modest host.

EukaHub is the successor to **Euka-Survey**, a Streamlit prototype, rebuilt on a
production-grade stack (PostgreSQL + FastAPI + a React/TypeScript SPA).

## Features

- **Genomic Resource Summary**: assemblies, annotations, and short/long-read
  RNA-Seq for any clade, with coverage meters over the full species count.
- **Quality dimension**: live BUSCO completeness, contig N50, genome size, and
  protein-coding gene counts, computed on demand from per-record tables.
- **Interactive radial Tree of Life**: a lazily-expanded dendrogram where node
  size scales with species count and colour encodes coverage for a chosen
  resource, with search-to-locate and a keyboard/screen-reader outline fallback.
- **Data map**: a click-to-drill treemap of a clade's subgroups. Area encodes
  magnitude and colour encodes a chosen coverage or quality "lens", so a big
  pale tile immediately reads as a large but under-studied group.
- **Compare groups**: put 2 to 6 clades side by side across coverage and quality.
- **Where are the gaps?** A ranked leaderboard of the clades with the most
  species and the least data, surfacing the project's core question directly.
- **Per-record drill-down**: browse the actual assemblies and annotations behind
  the numbers, with deep links out to NCBI and the source GFF files.
- **Wikipedia "About" cards**, a name/TaxID search scoped to Eukaryota, full
  **light and dark themes**, and a responsive layout down to mobile.

## Data sources

| Source | What it provides |
|---|---|
| **NCBI** (via the `datasets` CLI) | Genome assemblies + quality fields (assembly level, contig N50, genome size, GC) and the NCBI taxonomy (taxdump) |
| **Annotrieve** | Functional annotation metadata on the annotated subset (BUSCO, gene/transcript counts, source database, direct GFF links) |
| **ENA** | RNA-Seq run counts (short and long read) |

All ingested data is public. The pipeline caches each source as a local snapshot
so a rebuild is reproducible and re-runnable.

## Tech stack

- **Database**: PostgreSQL 17. The NCBI taxonomy is stored as an adjacency list
  (`parent_id`) plus an `ltree` lineage path, so a whole-subtree breakdown for
  any root is one indexed query. Feature counts are pre-rolled into a
  `clade_features` table; per-record `assembly`/`annotation` tables back the
  live quality statistics.
- **Backend**: FastAPI (Python), a read-only REST API with auto-generated
  OpenAPI. Pooled `psycopg`, SQL kept in one module, Pydantic response models
  derived from a single metric/quality config.
- **Frontend**: React + TypeScript (Vite + React Router SPA). The API's OpenAPI
  schema is compiled into typed TypeScript, so the client can't drift from the
  server.
- **Pipeline**: Python; taxonomy from the NCBI taxdump, assemblies via the NCBI
  `datasets` CLI, aggregation with Polars.
- **Packaging**: Docker + docker-compose; Python dependencies managed with
  [uv](https://docs.astral.sh/uv/) as a workspace (`core` / `api` / `pipeline`).

## Repository layout

```
core/       shared domain model: the metric + quality config (single source of truth)
api/        FastAPI service: the read-only REST API (auto-OpenAPI, typed to the SPA)
pipeline/   offline build: NCBI / Annotrieve / ENA fetch, Postgres load, clade rollup
web/        React + TypeScript SPA (Vite + React Router)
infra/      docker-compose (dev + prod) + the Postgres init schema
scripts/    dataset restore + auto-refresh, CI seed generation / loading, dataset summary
```

Python is a **uv workspace**; the frontend is a Vite SPA.

## Run it

You only need [Docker](https://docs.docker.com/) + Docker Compose. You do
**not** need to run the data pipeline: the dataset is built monthly on GitHub
Actions and published as a Release, and the stack installs it by itself.

```bash
git clone https://github.com/Cobos-Bioinfo/EukaHub.git
cd EukaHub
docker compose -f infra/docker-compose.prod.yml up --build -d   # web on http://localhost:8080
```

On first start the database is empty. The `refresher` service downloads the
latest published dataset (~50 MB), verifies it, and installs it, which takes a
few minutes; the site answers with "not found" until then. Afterwards it checks
for a newer Release once a day and swaps it in without downtime. Follow the
install with `docker compose -f infra/docker-compose.prod.yml logs -f refresher`,
and tear everything down with `docker compose -f infra/docker-compose.prod.yml down -v`.

Only the web port is published; Postgres and the API stay on the internal
network. The API docs are at http://localhost:8080/api/docs and the OpenAPI
schema at http://localhost:8080/api/openapi.json.

**Footprint.** The stack is sized for a small shared host: it has been tested
with **1 GB of RAM in total and a single CPU core** shared by all containers,
with no process killed. Postgres cancels any API query that runs longer than 15 s
(the client gets a clear 504), so one expensive request can't monopolize the
CPU. The database takes about 2.2 GB on disk, and an update briefly holds three
copies of it (the live one, the incoming one, and the previous one kept for
rollback).

Configuration is supplied via environment variables (never committed): database
credentials, the query time limit, the connection pool size, and caching. Copy
the template and set real values for a real deployment:

```bash
cp infra/.env.example infra/.env      # then edit; infra/.env is gitignored
```

## Development setup

Prerequisites: [Docker](https://docs.docker.com/) + Docker Compose,
[uv](https://docs.astral.sh/uv/), and Node.js 22+.

```bash
# 1. Install the Python workspace (core + api + pipeline + dev tools)
uv sync

# 2. Bring up Postgres (ships with the ltree + pg_trgm extensions)
docker compose -f infra/docker-compose.yml up -d db

# 3a. Load the published dataset (a few minutes; needs pg_restore 17, from the
#     postgresql-client-17 package)
uv run --package eukahub-pipeline python scripts/restore_snapshot.py \
  --url https://github.com/Cobos-Bioinfo/EukaHub/releases/latest/download/eukahub-dataset.dump

# 3b. ...or build it from the sources yourself. Only needed when working on the
#     pipeline: it downloads the NCBI taxdump and fetches every assembly,
#     annotation and RNA-Seq run from NCBI, Annotrieve and ENA, so it is slow.
#     Add --skip-download to reuse an unpacked taxdump.
uv run --package eukahub-pipeline python -m eukahub_pipeline.build

# 4. Run the API (http://localhost:8000, with /docs for the OpenAPI UI)
uv run --package eukahub-api uvicorn eukahub_api.main:app --reload

# 5. Run the web app in another terminal (proxies /api to the API)
cd web && npm install && npm run dev   # http://localhost:5173
```

Regenerate the typed API client after any API change:

```bash
cd web && npm run gen
```

## Tests

```bash
uv run pytest          # whole Python workspace (needs Postgres up)
cd web && npm run build # frontend typecheck + production build
```

Continuous integration runs ruff, the full pytest suite against a seeded
throwaway Postgres, the web typecheck/build, a gitleaks secret scan, and
dependency audits on every push. See `.github/workflows/`.

## Data refresh

The serving dataset is rebuilt offline, never edited in place. A scheduled
GitHub Actions workflow (`.github/workflows/rebuild.yml`) re-fetches all sources
monthly, rebuilds the database, gates on the pipeline's invariant checks, and
publishes a validated `pg_dump` snapshot as a public GitHub Release. A running
stack's `refresher` service picks it up within a day: it restores the snapshot
into a staging database, verifies it, and only then swaps it in, keeping the
previous dataset for a one-command rollback
(`scripts/restore_snapshot.py --rollback`). If a download or verification fails,
the live dataset is left untouched. You can also trigger a rebuild on demand
from the Actions tab.

## Acknowledgements

EukaHub builds on **Euka-Survey** and reuses its metric definitions and rollup
semantics. Genomic and taxonomic data come from NCBI, Annotrieve, and ENA.

## License

Released under the [MIT License](LICENSE).
