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

## Open — still to decide

- **React meta-framework:** Next.js vs Vite + React Router. Lean Vite (pure
  API-backed SPA); revisit if SSR of clade pages matters.
- **Tree encoding in Postgres:** `ltree` path vs integer-array ancestors
  (`ltree` preferred for its operators + GiST index).
- **Rollup engine:** DuckDB vs Polars (pick at Phase 1).
