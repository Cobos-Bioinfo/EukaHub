# Decision log

ADR-style. Settled decisions with a one-line why; open forks at the bottom.

## Settled (2026-07-25)

- **Drop ETE3 entirely** (build + runtime). Unmaintained, `numpy<2` pin, PyQt5,
  slow cold-start build. Taxonomy moves into our own DB, loaded from NCBI taxdump.
- **Drop the ETE3/PyQt5 tree rendering.** Question 2 is served by a table/chart
  now, an interactive Tree of Life later.
- **DB engine: PostgreSQL** (over MongoDB). Purpose-built for hierarchy + tabular
  metrics (`ltree`, recursive CTEs) and the broadest, most transferable skill.
  Mongo (guigolab's default) also fit; Docker keeps that deploy path open.
- **Serving DB is row-oriented & relational, not a graph DB.** A taxonomy is a
  strict single-parent tree — adjacency + materialized lineage beats Cypher
  traversal. Columnar (DuckDB/Polars) is for the offline rollup only.
- **Tree storage: adjacency (`parent_id`) + materialized lineage together.**
  Kills `precomputed_taxa`; the breakdown becomes one indexed query for any root.
- **Backend: FastAPI (Python).** Reuses the domain logic + pipeline; auto-OpenAPI
  matches guigolab's API-spec convention.
- **Frontend: React + TypeScript** (over Vue). User interest, largest market, and
  the deepest ecosystem for the eventual WebGL Tree of Life.
- **Packaging: Docker + docker-compose.** Matches the deploy host.

## Settled (2026-07-29)

- **Tree encoding: `ltree` path** (over integer-array ancestors). The GiST
  index plus the `@>`/`<@` ancestor/descendant operators are purpose-built for
  this; integer arrays buy nothing here.
- **Frontend build: Vite + React Router** (over Next.js). Pure API-backed SPA;
  no SSR need today. Revisit only if server-rendering clade pages matters.
- **Python dependency management: uv** (`pyproject.toml` + `uv.lock`), as in
  Euka-Survey. A uv **workspace** splits deps per service — `core` (shared
  domain model), `api`, `pipeline`.

## Open — still to decide

- **Rollup engine:** DuckDB vs Polars — pick at Phase 1 when the roll-up is
  written. **Pandas is ruled out**: the ~30–45M-row lineage explosion is a
  columnar scan/join/group-by that wants a parallel, larger-than-memory engine;
  Pandas is eager, single-threaded, RAM-bound, and is the tool this rewrite
  moves away from. Both finalists fit; the choice is SQL-flavor (DuckDB) vs
  dataframe-flavor (Polars).
