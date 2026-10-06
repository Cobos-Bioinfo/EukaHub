# Architecture

EukaHub is a read-only web app over a dataset that is rebuilt offline once a month.
That single fact shapes the design: the server never writes, so the data can be
heavily precomputed and denormalized, and an update is just "install a new copy".

## Components

```
GitHub Actions, monthly                          Server, docker compose
─────────────────────────────                    ──────────────────────────────────────────
NCBI datasets ┐                                  refresher  (daily: is there a newer Release?)
Annotrieve    ├─► pipeline ─► pg_dump ─► Release ─────► db   Postgres 17 + ltree + pg_trgm
ENA           ┘   (rebuild.yml)          (public)          ▲
                                                           api  FastAPI, read-only
                                                           ▲  /api
                                              browsers ─► web  nginx: SPA, API proxy, cache
```

| Component | Code | Role |
|---|---|---|
| Pipeline | `pipeline/` | Downloads the NCBI taxonomy and every eukaryotic assembly (NCBI `datasets`), annotation (Annotrieve) and RNA-Seq run count (ENA); rolls counts up the tree; loads Postgres; checks invariants. Runs on GitHub Actions, never on the server. |
| Rebuild workflow | `.github/workflows/rebuild.yml` | Monthly (and on demand): runs the pipeline, gates on the invariant checks, publishes a `pg_dump` as a GitHub Release. |
| Database | `infra/postgres/init/001_schema.sql` | Postgres 17. See [data-model.md](data-model.md). |
| API | `api/` | FastAPI, read-only, auto-generated OpenAPI at `/api/docs`. One module per resource in `api/src/eukahub_api/resources/`, mapped together in `router.py`; endpoint SQL lives in `api/src/eukahub_api/queries.py`. |
| Web | `web/` | React + TypeScript SPA built with Vite, served by nginx, which also proxies `/api` and caches API responses. |
| Refresher | `scripts/auto_refresh.py` + `scripts/restore_snapshot.py` | Sidecar container. Installs the latest dataset Release on first start, then checks daily for a newer one. |
| Shared config | `core/src/eukahub_core/metrics.py`, `taxonomy.py` | The four resource metrics, the quality stats and the root taxids, shared by pipeline and API and exported to the web app through OpenAPI. |
| Deployment settings | `api/src/eukahub_api/settings.py`, `infra/config/` | Links, privacy contact, Wikipedia summary endpoint, curated groups and custom groups, read by the API at startup. The web app gets them, with the custom groups, from `/api/config`, and the data of any set of clades from `/api/taxons/aggregates`. See [deployment.md](deployment.md#configuration). |

## Request path

Browser → nginx (static SPA; `/api/*` proxied, successful GETs cached for up to
an hour) → FastAPI → Postgres. Successful API responses carry `Cache-Control`,
and JSON responses an `ETag`. Nothing in the request path writes to the database or calls an external
service. The Wikipedia summary on the dashboard is fetched by the browser from
Wikipedia.

## Data updates

1. On the 1st of each month, `rebuild.yml` builds the dataset from fresh sources
   into a throwaway Postgres, runs the invariant checks, and publishes the dump as
   Release `dataset-YYYYMMDD` (asset `eukahub-dataset.dump`, about 50 MB). A build
   that fails the checks publishes nothing; a failed scheduled build also opens an
   issue in the repository.
2. The refresher on each server polls the repository's latest Release once a day.
   When it is newer than the loaded dataset (or nothing is loaded), it downloads the
   dump, checks it against the size and SHA-256 digest GitHub publishes for the
   asset, restores it into `<db>_next`, collects planner statistics there (a dump
   carries none, and without them the first queries after the swap time out),
   runs the same invariant checks, and swaps databases by renaming: `<db>` becomes
   `<db>_prev`, `<db>_next` becomes `<db>`. Open database sessions are closed
   during the swap, which takes about a second.
3. If anything fails before the swap, the live database is untouched. A Release
   that fails three times is skipped until a newer one appears.

No credentials are involved: the Release is public and the server only makes
outbound HTTPS requests. See [deployment.md](deployment.md) for operating it.

## Resource budget

The stack is designed for a small shared host: about 1 GB of RAM in total and one
CPU core. It has been tested under exactly those limits (see
`infra/lowmem-test/`). The main levers:

- Postgres cancels any API query after 15 s (`DB_STATEMENT_TIMEOUT_MS`); the client
  gets a 504 and the CPU is freed.
- The API holds at most 4 database connections (`DB_POOL_MAX`); excess requests
  wait, then get a 503 with `Retry-After`.
- Parallel query workers and JIT are off in the production Postgres, since they
  only compete for the single core.
- nginx caches API responses, so repeated views of popular clades never reach the
  database.

## Repository layout

```
core/       metric, quality-stat and taxonomy definitions shared by pipeline and API
pipeline/   offline build: fetch, roll up, load, validate
api/        FastAPI service and its tests (api/tests/seed.sql is the CI dataset)
web/        React SPA, nginx config, production Dockerfile
infra/      docker-compose files, Postgres schema, refresher image, groups file, low-memory test
scripts/    restore/refresh tooling and CI dataset helpers
docs/       these documents
```
