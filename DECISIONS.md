# Decision log

Lightweight ADR-style record. Newest context at the top of each entry.

## Settled

- **Drop ETE3 entirely.** Friction (unmaintained, `numpy<2` pin, PyQt5,
  cold-start taxonomy build). Taxonomy moves into our own DB, loaded from NCBI
  taxdump. (2026-07-25)
- **Drop the ETE3/PyQt5 tree rendering.** No longer seen as useful; removes the
  subprocess/OOM machinery. Question 2 is served by a table/chart now, an
  interactive Tree of Life later. (2026-07-25)
- **Backend: FastAPI (Python).** Reuses the domain logic + pipeline; auto-OpenAPI
  matches guigolab's API-spec convention. (2026-07-25)
- **Packaging: Docker + docker-compose.** Matches the deploy host; good practice.
  (2026-07-25)
- **Serving DB is row-oriented & relational-style; not a graph DB.** The
  taxonomy is a strict tree, best served by adjacency + materialized lineage,
  not Cypher traversal. Columnar (DuckDB/Polars) is for the offline rollup only.
  See [`docs/data-model.md`](docs/data-model.md). (2026-07-25)
- **Tree storage: adjacency (`parent_id`) + materialized lineage (path/ancestors)
  together.** Kills `precomputed_taxa`; makes the breakdown a single indexed
  query for any root. (2026-07-25)
- **D1 — Database engine: PostgreSQL.** Chosen over MongoDB. Both fit the
  read-only workload, but Postgres is the textbook fit for hierarchy + tabular
  metrics (`ltree` is purpose-built for taxonomies; recursive CTEs), the
  broadest/most-transferable skill, and the stronger general showcase. Docker
  keeps the guigolab deploy path open regardless of their Mongo default.
  (2026-07-25)
- **D2 — Frontend framework: React (+ TypeScript).** Chosen over Vue. The
  user's stated interest and the largest job market, with the deepest ecosystem
  for the eventual WebGL Tree of Life (deck.gl, react-three-fiber, visx). Meta-
  framework (Next.js vs Vite) still to decide at scaffold time. (2026-07-25)

## Open — still to decide

- **Meta-framework for React:** Next.js (SSR/SSG, file routing, Vercel) vs
  Vite + React Router (pure SPA). Lean Vite for a pure API-backed SPA; revisit
  if SEO/SSR of clade pages becomes a goal.
- **Tree encoding specifics in Postgres:** `ltree` path vs integer-array
  ancestors (both viable; `ltree` preferred for its operators + GiST index).
- **Rollup engine in the pipeline:** DuckDB vs Polars (both fine; pick at
  Phase 1).
