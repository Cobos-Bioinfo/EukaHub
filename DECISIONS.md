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
- **Rollup engine: Polars** (over DuckDB; Pandas ruled out). Chosen and
  validated at Phase 1: inputs originate in-process (parsed taxdump) plus a
  small SQLite read, which Polars ingests natively with no extension/file
  bridge, and the lineage fan-out reads idiomatically as `split → explode →
  group_by`. The ~50M-row explode+group-by (1.9M species → 1.83M clades) runs
  in ~3 s and reproduces Euka-Survey's numbers within 0.3%. DuckDB stays a
  viable alternative; Pandas is eager/single-threaded/RAM-bound and is the tool
  this rewrite moves away from.

## Settled (2026-07-31)

- **Secrets via env substitution, not committed.** `infra/docker-compose.yml`
  reads `${POSTGRES_USER/PASSWORD/DB:-eukahub}` (dev defaults keep local dev
  zero-config) and builds `DATABASE_URL` from them; `infra/.env.example` is the
  committed template, `infra/.env` is gitignored. Real credentials come from a
  secret store at deploy time. Full production hardening (no public `5432`, TLS,
  CORS, rate limiting, security headers, the read-only-API auth decision) is
  scheduled and enumerated in roadmap Phase 5 — **the assistant owns security
  and credentials** and must action those steps when Phase 5 reaches them.

## Open — still to decide

- None — all forks resolved.
