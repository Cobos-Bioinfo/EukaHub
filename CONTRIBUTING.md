# Contributing to EukaHub

Thanks for helping. Bugs and ideas go in
[GitHub issues](https://github.com/Cobos-Bioinfo/EukaHub/issues) (the forms ask for
what we need); people without a GitHub account can use the feedback form linked in
the app's menu. For how the system fits together, read
[docs/architecture.md](docs/architecture.md) first.

## Development setup

Prerequisites: Docker with Compose, [uv](https://docs.astral.sh/uv/), Node.js 22+,
and `pg_restore` 17 (package `postgresql-client-17`) to load the dataset.

```bash
# 1. Python workspace (core, api, pipeline and dev tools)
uv sync

# 2. Postgres with the ltree and pg_trgm extensions, on localhost:5432
docker compose -f infra/docker-compose.yml up -d db

# 3a. Load the published dataset (a few minutes)
uv run --package eukahub-pipeline python scripts/restore_snapshot.py \
  --url https://github.com/Cobos-Bioinfo/EukaHub/releases/latest/download/eukahub-dataset.dump

# 3b. ...or build it from the sources. Only needed for pipeline work: it downloads
#     the NCBI taxonomy and fetches every assembly, annotation and RNA-Seq count,
#     which takes a while. Needs the NCBI `datasets` CLI on PATH.
uv run --package eukahub-pipeline python -m eukahub_pipeline.build --refresh-sources

# 4. API on http://localhost:8000 (OpenAPI UI at /docs)
uv run --package eukahub-api uvicorn eukahub_api.main:app --reload

# 5. Web app on http://localhost:5173 (proxies /api to the API)
cd web && npm install && npm run dev
```

If the database container cannot bind port 5432, another Postgres (often a
system-installed one) is using it: stop that service or change its port.

## Checks to run before a pull request

```bash
uv run ruff check .       # Python lint
uv run pytest             # Python tests (need the dataset loaded, step 3)
cd web && npm run build   # TypeScript typecheck + production build
```

CI runs the same checks plus a secret scan and dependency audits
(`.github/workflows/ci.yml`). In CI the API tests run against a small, consistent
slice of the real dataset (`api/tests/seed.sql`) instead of the full one, so tests
must hold on both: assert relationships (a clade's species count equals the count
of species below it, results are sorted, limits are honoured) rather than fixed
numbers. To reproduce CI locally, load the slice into a scratch database. This
truncates the target, so never point it at your working database:

```bash
psql postgresql://eukahub:eukahub@localhost:5432/postgres -c "CREATE DATABASE eukahub_ci"
DATABASE_URL=postgresql://eukahub:eukahub@localhost:5432/eukahub_ci uv run python scripts/load_ci_db.py
DATABASE_URL=postgresql://eukahub:eukahub@localhost:5432/eukahub_ci uv run pytest
```

`scripts/generate_ci_seed.py` regenerates the slice from a full database; only
needed when the schema or the taxa the tests rely on change.

## Changing the API

The web app's TypeScript types are generated from the API's OpenAPI description.
After changing an endpoint or a response model, regenerate and commit both files:

```bash
cd web && npm run gen    # writes web/src/api/openapi.json and schema.ts
```

Endpoint SQL lives in `api/src/eukahub_api/queries.py`, response models in
`schemas.py`, and the resource and quality-stat definitions shared with the
pipeline in `core/src/eukahub_core/metrics.py`. Keep API queries within the
resource budget in [docs/architecture.md](docs/architecture.md#resource-budget):
anything that scans a large part of the taxonomy per request needs a plan for the
one-core production host.

## Branches and commits

- `main` holds released work; `dev` is where work lands. Open pull requests against
  `dev`.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/):
  `feat(web): ...`, `fix(api): ...`, `docs: ...`, with a body explaining why.

## Code conventions

- **Comments:** code should explain itself through names and structure. Keep
  comments short: a docstring saying what a function is for, and a note where the
  reason is not obvious from the code.
- **Python:** ruff, line length 100. SQL identifiers that are interpolated must come
  from a fixed set (an enum or the metric config), never from request input.
- **TypeScript:** strict mode; data fetching through `web/src/api/queries.ts` and
  the `useAsync` hook.
- **Interface text:** plain, short sentences; no em dashes and no emojis. Icons are
  inline SVG components in `web/src/components/icons.tsx`.
- **Colours:** use the CSS variables in `web/src/index.css`, which define both the
  light and the dark theme. Check new views in both themes and at phone width
  (about 390 px).
- **Charts:** every chart has a text alternative (a list, table or outline), and
  colour is never the only way a value is shown.

## License

By contributing you agree that your contributions are released under the
[MIT License](LICENSE).
