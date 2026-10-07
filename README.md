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
- **Quality dimension**: best BUSCO completeness and median contig N50, genome
  size and protein-coding gene counts for every clade, computed at build time from
  per-record tables.
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
- **Wikipedia "About" cards**, a name/TaxID search scoped to Eukaryota that puts
  the best-covered groups first and suggests close spellings, full **light and
  dark themes**, and a responsive layout down to mobile.

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
  `clade_features` table and each clade's quality statistics into `clade_stats`;
  per-record `assembly`/`annotation` tables back the record lists.
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
infra/      docker-compose (dev + prod), the Postgres schema, a low-memory test harness
scripts/    dataset restore + auto-refresh, CI seed generation / loading, dataset summary
docs/       architecture, deployment, data model, design decisions
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
for a newer Release once a day and swaps it in, with about a second of
interruption. Follow the
install with `docker compose -f infra/docker-compose.prod.yml logs -f refresher`,
and tear everything down with `docker compose -f infra/docker-compose.prod.yml down -v`.

Only the web port is published; Postgres and the API stay on the internal
network. The API docs are at http://localhost:8080/api/docs and the OpenAPI
schema at http://localhost:8080/api/openapi.json.

**Footprint.** The stack is sized for a small shared host: it has been tested
with **1 GB of RAM in total and a single CPU core** shared by all containers,
with no process killed. Postgres cancels any API query that runs longer than 15 s
(the client gets a clear 504), so one expensive request can't monopolize the
CPU. The database takes about 1 GB on disk, and an update briefly holds three
copies of it (the live one, the incoming one, and the previous one kept for
rollback).

Configuration (credentials, limits, caching, which repository to take data from,
external links and the featured groups) comes from environment variables in
`infra/.env` and an optional groups file; start from
`infra/.env.example`. [docs/deployment.md](docs/deployment.md) covers
configuration, running behind a TLS proxy, data updates, rollback and running
from a fork.

## Documentation

- [Architecture](docs/architecture.md): components, request path, data updates,
  resource budget.
- [Deployment and operations](docs/deployment.md): install, configuration, TLS,
  updates, forks.
- [Data model](docs/data-model.md): what each number means and how it is stored.
- [Design decisions](docs/decisions.md): why it is built this way.
- [Contributing](CONTRIBUTING.md): development setup, tests, conventions.

## Data refresh

The dataset is rebuilt from the sources every month by a GitHub Actions workflow
(`.github/workflows/rebuild.yml`), checked, and published as a public Release;
running servers install it on their own within a day, and keep the previous
dataset for rollback. Details in [docs/architecture.md](docs/architecture.md#data-updates).

## Acknowledgements

EukaHub builds on **Euka-Survey** and reuses its metric definitions and rollup
semantics. Genomic and taxonomic data come from NCBI, Annotrieve, and ENA.

## License

Released under the [MIT License](LICENSE).
