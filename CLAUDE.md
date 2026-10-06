# CLAUDE.md

Guidance for AI coding agents working in this repository. Human documentation is
`README.md`, `CONTRIBUTING.md` and `docs/`; read `docs/architecture.md` before larger
changes. Put personal or machine-specific notes in a gitignored `CLAUDE.local.md`.

## Project
- EukaHub: explorer of public genomic-data availability across Eukaryota. Per taxon: a
  dashboard, a click-to-drill treemap ("data map"), a radial Tree of Life, compare, and a
  gaps leaderboard.
- Sources: NCBI `datasets` CLI (assemblies), Annotrieve `api/v0` (annotations, BUSCO),
  ENA (RNA-Seq run counts). Rewrite of Euka-Survey (Streamlit).
- The dataset is rebuilt monthly on GitHub Actions (`.github/workflows/rebuild.yml`),
  published as Release `dataset-YYYYMMDD` (asset `eukahub-dataset.dump`), and installed by
  each server's refresher (`scripts/auto_refresh.py`). Serving is read-only.
- Production budget: about 1 GB RAM and one CPU core, running unattended for years. Judge
  every change against that: nothing that needs a human, a token, or a spare core.

## Map
| Path | Notes |
|---|---|
| `core/src/eukahub_core/metrics.py` | `METRICS`, `QUALITY_STATS`, `CladeMetadata`, shared by pipeline and API and exported to the web app via OpenAPI. The schema SQL, `rollup._subtree_totals` and `validate._COLS` are kept in sync by hand. |
| `pipeline/src/eukahub_pipeline/build.py` | taxdump → Eukaryota trim → fetch (parquet cache in `data/sources/`) → `drop_duplicate_assemblies` → `prune_placeholders` → rollup (Polars) → load → `check_invariants` → `dataset_meta` last |
| `api/src/eukahub_api/` | `main.py` routes and middleware; `queries.py` all SQL (`_quality_by_bucket` is the per-bucket stats helper); `schemas.py`; `db.py` connection pool; `settings.py` deployment settings (env + `infra/config/groups.json`, served by `/config`); `clade_sets.py` sets of clades (include minus exclude) and the custom groups built from them |
| `web/src/` | `api/queries.ts` (all fetches), generated `api/openapi.json` + `schema.ts`; `hooks/useAsync` (results keyed by deps, `reload()`); `hooks/useTree` (visible-node cap); colours are CSS variables in `index.css` |
| `infra/` | `docker-compose.yml` (dev DB), `docker-compose.prod.yml` (db, api, web, refresher), `postgres/init/001_schema.sql` (schema of record), `lowmem-test/` (1 GB / one-core harness) |
| `scripts/` | `restore_snapshot.py` (stage, verify, rename swap, `--rollback`), `auto_refresh.py`, `generate_ci_seed.py` + `load_ci_db.py` (CI dataset) |

## Commands
- Setup, running, tests, CI dataset: `CONTRIBUTING.md`.
- Before committing: `uv run ruff check .`, `uv run pytest` (needs the dataset loaded),
  `cd web && npm run build`.
- After any API schema change: `cd web && npm run gen`, and commit `openapi.json` + `schema.ts`.
- `scripts/load_ci_db.py` truncates its target database: use a scratch database only.
- `uv add`/`uv remove --package X` re-syncs the venv for X only; run `uv sync` afterwards.
- UI checks in a browser: build the web app, run the API, then
  `VITE_API_URL=http://localhost:<port> web/node_modules/.bin/vite preview` (plain `npx vite`
  ignores the project config and its `/api` proxy). Check light, dark and ~390 px width.

## Invariants
- No ETE3 and no per-root precomputed tables: a breakdown is one indexed `ltree` subtree
  query for any root.
- `taxon` holds Eukaryota (2759) plus its two ancestors (1, 131567). No foreign keys.
  These taxids come from `eukahub_core.taxonomy` (web: `lib/taxonomy.ts`), never literals.
- Deployment-specific values (links, contact, Wikipedia, curated groups, source URLs)
  are settings with code defaults: the API falls back on an invalid value, the
  pipeline (`sources.py`) fails.
- `n_rows` counts species (formal names, with or without data); `s_*` count every record
  in the subtree at any rank; `c_*` count species with data on themselves or below. Informal
  species and below-species taxa are single units (`n_rows = 1`). Placeholder taxa without
  data are dropped at build time (`placeholders.py`). One `assembly` row per
  assembly number (GenBank over RefSeq, latest version).
- Counts are rolled up at build time; medians and best-of stats are computed per request
  from the record tables.
- `dataset_meta` is written last; its presence marks a complete build. The update swap
  renames databases (the extensions live in `public`).
- Tests pass on both the full dataset and the CI slice (`api/tests/seed.sql`): assert
  relationships, never fixed counts.

## Performance rules
- API connections have a 15 s statement timeout, a 4-connection pool and
  `plan_cache_mode=force_custom_plan`: generic plans lose the literal root path and scan the
  whole 400 MB path index.
- Subtree filters take the root's path as a literal parameter (`path <@ %s::ltree`), never a
  subquery. Don't join records to buckets by ltree containment; resolve ancestors from the
  path labels (see `_quality_by_bucket`).
- Check new queries with `EXPLAIN (ANALYZE, BUFFERS)` on the full dataset with
  `max_parallel_workers_per_gather=0`, as in production.

## Conventions
- Code comments: code should explain itself; keep a short docstring saying what a function
  is for and a comment only where the reason is not obvious. No history narration.
- Public docs change in the same commit as the behaviour they describe; new design
  decisions go to `docs/decisions.md`.
- Interface text: plain sentences, no em dashes (except "—" as an N/A placeholder), no emojis.
  Icons are inline SVG in `web/src/components/icons.tsx`.
- Charts: one sequential ramp per measure, light to dark in both themes, and a text
  alternative (list, table or outline) for every chart.
- Commits: Conventional Commits with a body explaining why; pull requests target `dev`.
  Commit or push only when asked.
- Security: never commit secrets or print tokens. SQL identifiers interpolated into queries
  must come from a fixed set (an enum or the metric config), never from request input.
