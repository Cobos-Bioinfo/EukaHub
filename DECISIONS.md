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
- **No user auth on the API (public, read-only, public data).** The API serves
  only publicly-available genomic-resource counts derived from NCBI / Annotrieve
  / ENA — nothing user-specific or sensitive, no write path — so authentication
  buys nothing. If scraping/abuse appears, add **gateway rate limiting** and/or
  **optional API keys for quota**, not login. Revisit only if a non-public
  dataset or a write path is introduced.
- **Wikipedia "About" card fetched via the API, not the browser.** The
  decorative summary (`GET /taxon/{taxid}/about`) is proxied server-side rather
  than fetched client-side, for four reasons: (1) Wikipedia's REST policy wants
  a descriptive `User-Agent`, a header browser `fetch` can't set; (2) it fits
  the typed-bridge pattern (OpenAPI → TS → `getAbout(taxid)`); (3) it rides the
  existing `Cache-Control` middleware plus a 24h in-process TTL cache, so at
  most one Wikipedia hit per taxon — the "no article" (`null`) result caches
  too; (4) same-origin `/api` avoids a CSP `connect-src` change. This is the
  **first external call in the read path** — kept non-load-bearing (any failure
  → `null` → the card is omitted) and SSRF-free (URL fixed to the summary
  endpoint, name URL-encoded; stdlib `urllib`, no new dep). **Follow-up:** when
  a CSP lands (with TLS), allow `img-src https://upload.wikimedia.org` for the
  thumbnail, or proxy the image too.
- **Deployment target: CRG / guigolab server — deferred.** Deploy only once the
  app is more functionally interesting; then, with **Guigó** and the team's **IT
  expert**, deploy on CRG/guigolab's Docker-based infra (matches our
  docker-compose; intended shape = "small VPS + Docker"). Until that
  conversation the deploy-dependent Phase 5 items (scheduled rebuild vs. the
  live DB, TLS, staging/prod DB, gateway rate limiting) are on hold — they
  depend on CRG's environment. The app is already deploy-agnostic-ready.

## Settled (2026-08-01)

- **Phase 6 tree = radial dendrogram, rendered in SVG.** The interactive Tree of
  Life is a *radial* node-link tree (the iconic, most recognizable "tree of
  life" form for a biology audience), chosen with the user over an
  indented outliner / icicle-sunburst / horizontal dendrogram. Rendered as
  **React-controlled SVG** (accessible, themeable, consistent with the hand-built
  divergent chart), bounded by lazy-expand + a visible-node guardrail — so
  Canvas/WebGL (the roadmap's original aspiration) is deferred as a scale-up
  path, not needed for the MVP.
- **New runtime dep: `d3-hierarchy` + `d3-shape` (layout math only).** Radial
  tidy-tree geometry + curved-link generators are error-prone to hand-roll; these
  two focused modules (~19 KB gz, TS types) do just the math while we keep all
  rendering in our SVG. Vetted: they add **zero** npm-audit advisories (the only
  2 highs remain react-router; the dev-only openapi-typescript chain has since
  cleared upstream). A hand-rolled polar layout was the zero-dep alternative.
- **Tree lazy-expand via a dedicated `GET /taxon/{taxid}/children`.** Direct
  children by adjacency (`parent_id`), sorted by species count, paginated
  (limit/offset), with a per-child `has_children` flag (an indexed `EXISTS`
  probe) so the UI shows an expand affordance without a round-trip. This is the
  cheap adjacency lookup the schema reserved `parent_id` for. The `EXISTS` probe
  is fine for the MVP; a precomputed `child_count` rollup column is a future
  optimization (needs a pipeline change + rebuild). Node **colour** encodes a
  single sequential metric (assembly coverage %), not a categorical palette, so
  the dataviz categorical-separation validator doesn't apply.

## Settled (2026-08-02) — data-model & pipeline enrichment

The pipeline moves off the Phase-1 SQLite bridge to fresh sources, and the data
model grows from **counts-only** to a **hybrid** that captures per-record
metadata. The old model reduced every source to `{taxid: count}` and discarded
everything the fetches returned; the redesign stops discarding it.

- **Hybrid storage (over aggregates-only / full-per-record).** Per-record tables
  for **assemblies** and **annotations** (bounded: ~68k + ~17k rows), plus the
  extended additive `clade_features` rollup. **Reads stay aggregated per taxon**
  — ENA RNA-Seq is ~8.2M runs, too many to serve per-record for the value. This
  gives drill-down + deep-links where it's cheap, without a giant reads table.
- **Source split (effort-optimal).**
  - **NCBI `datasets` CLI → all assemblies + their quality fields.** We already
    call it; we just **stop discarding** `assembly_level`, `contig_n50`,
    `total_sequence_length`, `gc_percent`, `refseq_category`, `release_date`,
    `submitter`, `bioprojects`, FTP url. Assembly quality covers **100%** of the
    ~68k assemblies.
  - **Annotrieve (`api/v0`) → annotation richness.** Replace the thin
    `frequencies/taxid` call with `/annotations` (paginated) to pull **BUSCO**
    (`complete`/`single_copy`/`duplicated`), **gene counts**
    (`root_type_counts.gene`, `protein_coding`), transcript stats, source-DB mix,
    and the direct **GFF `url_path`**. This is where Annotrieve saves us the most
    effort (we'd otherwise compute BUSCO/gene counts ourselves).
  - **ENA → reads**, unchanged in source, kept aggregated as two run-count
    metrics (no `base_count`; see below).
- **Annotrieve enriches, does not replace, the assembly count.** Its assembly
  collection is the **annotated subset** — `/assemblies/frequencies/assembly_level`
  totals **16,905** (Complete 446 / Chromosome 6,449 / Scaffold 6,677 / Contig
  3,333), versus our **67,659** total assemblies. So the authoritative count still
  comes from `datasets`; Annotrieve supplies quality on the annotated ~25%.
- **New "annotation-quality" dimension (surfaced).** BUSCO complete % and
  protein-coding gene count become headline stats + sortable breakdown columns —
  a genuinely new capability, scoped to the reference-quality core (~17k
  annotated genomes, ~8.5k taxa; the fraction the coverage check quantified).
- **Distribution stats are computed on demand, not precomputed.** Counts roll up
  by summation (additive: `clade_features` gains assembly-level composition
  counts `n_ass_complete/_chromosome/_scaffold/_contig` and `n_reference` via the
  same explode→sum). **Medians/percentiles do not** (median of a subtree ≠ sum of
  medians), so median N50 / genome size / gene count / BUSCO are computed live
  from the small per-record tables via an `ltree` subtree aggregation. The
  per-record tables (~68k / ~17k rows) make live stats + record lists cheap, so
  we avoid a heavy per-clade quality rollup.
- **RNA-Seq reads: run counts only, no `base_count`/`s_bases`** (user, 2026-08-02).
  Reads keep the two existing count metrics (`rna` = any-platform runs, `lng` =
  long-read runs); we do not add sequencing volume. Keeps reads parallel to the
  other three resources and the ENA fetch unchanged (`fields=tax_id,
  instrument_platform`).
- **Sequence: data model first, then the breakdown redesign** on top of the new
  columns (the breakdown was "sparse 4 bars"; enrich the data before redesigning
  its presentation).
- **Coupling to a live CRG API is acceptable and synergistic.** Sourcing
  annotations from Annotrieve makes us a downstream consumer of a guigolab
  resource — good alignment for the eventual CRG deploy — but the offline build
  keeps the resumable-snapshot + atomic-swap discipline and pins `api/v0`, so a
  transient Annotrieve outage never corrupts a served dataset.

## Settled (2026-08-02) — breakdown redesign (the "data map")

- **The rank breakdown is reimagined as a click-to-drill treemap ("data map"),
  not a table/chart** (user, 2026-08-02). Design-first: three directions were
  prototyped/offered — a **ranked leaderboard**, a **heatmap matrix**, and this
  **proportional treemap** (plus a mentioned scatter "opportunity map"). The user
  rejected the first ASCII round ("felt secondary… cumbersome… all those
  dropdowns"), asked for something *central, clear, fun, and genuinely novel that
  doesn't just re-list Annotrieve*, and after seeing a live prototype picked the
  **treemap** ("fun, interactive, truly a dashboard"). Rationale: it's the app's
  signature question ("where is genomic data across the tree, and where are the
  gaps?"), and a proportional map answers it at a glance — **big + pale = a large
  clade nobody has sequenced**.
- **Drill by clicking to the next *meaningful* rank — no rank dropdown.** Immediate
  adjacency children fail on taxonomy (Mammalia → Theria holds ~all species), so
  the map jumps to the next canonical rank below the focus (class → orders →
  families → genera); rank is implicit in drill depth. This kills the old five
  dropdowns (rank/sort/filter/logic/limit) — the only controls are two segmented
  toggles (Colour-by lens, Size-by). Distinct from the Tree of Life (topology /
  adjacency); the map is quantitative data-distribution at ranks.
- **Colour = one theme-aware sequential ramp; lenses swap the *measure*, not the
  hue** (dataviz skill). Percentage lenses fill 0–100; magnitude lenses (median
  genes / genome size) normalise to the largest tile in view and show that max in
  the legend. Null = grey (the gap). Ordinal ramp `lib/ramp.ts` shared with the
  radial tree.
- **Per-tile quality via a new endpoint, not the additive rollup.** `GET
  /clade/{taxid}/breakdown/quality?rank=R` computes per-bucket distribution stats
  (best BUSCO, median genes/genome-size/N50) in **one grouped `ltree` query per
  source** (each record attributed to its rank-R ancestor). A subtree median isn't
  additive, so it can't ride `clade_features` — consistent with the Stage-C live
  stats. Fetched async so the map paints instantly. Worst case ~1 s
  (Eukaryota→phylum); acceptable async + cached, optimisation candidate later.
- **The map replaced the old breakdown** (promoted 2026-08-02, commit `8ffb026`).
  Extracted into a reusable `BreakdownMap`; it is the dashboard's Breakdown section
  (embed variant) and the standalone `/map/:taxid` page (nav "Data map", no beta).
  `BreakdownSection`/`DivergentBarChart`/`lib/breakdown` are deleted. The TSV export
  (`export.tsv`) is preserved as a "Download TSV" action; the old client-side
  "displayed rows" export was dropped. Accessibility is a **"View as a list"**
  fallback (the map's analogue of the tree's `TreeOutline`), since a treemap is not
  keyboard-navigable on its own.
- **House style / no AI-writing tells in UI copy** (user, 2026-08-02). No em dashes
  in user-facing copy (they read as machine-written and break house style); em
  dashes only survive as the N/A placeholder glyph and in code comments (matching
  the existing codebase). See the writing-style memory.

## Settled (2026-08-04) — pre-deploy polish batch

- **Gaps quality via a taxid-scoped stats query, not the full breakdown.** `/gaps`
  attaches per-clade quality (best BUSCO / median coding genes / genome size / N50)
  through `fetch_quality_for_taxids`, which reuses the two-phase shape of
  `fetch_breakdown_quality` but buckets on the explicit set of returned taxids.
  Reusing `fetch_breakdown_quality(root, rank)` instead would compute *every*
  bucket: measured at the gaps default (Eukaryota -> order) that is 907 buckets in
  ~5.2s vs ~0.4s for the top 25 the leaderboard actually shows. It is **gated
  behind `include_quality`** (default on) because the scan cost is independent of
  `limit`; the landing teaser passes `false` so it stays light.
- **Gaps scatter is a single-series bubble chart** (dataviz skill): x = species
  (log, padded to whole-power ticks), y = coverage %, bubble size = the gap, one
  `--gap` amber (already validated as the leaderboard gap bar, so no categorical
  palette to validate), per-mark hover tooltip. No legend (single series, the title
  names it); the **List view is the accessible table fallback** (same pattern as the
  treemap's "view as a list" and the tree's outline). Chosen over recolouring by
  gap magnitude, since bubble size already carries the gap.
- **ETag = a weak tag over the buffered JSON body, in the response middleware.**
  BaseHTTPMiddleware exposes only a streaming wrapper (no `.body`), so the
  middleware **buffers `application/json` GET bodies** to fingerprint them (cheap
  for these small payloads) and returns a bodyless **304** on a matching
  `If-None-Match`. Weak comparison (RFC 7232); `md5(usedforsecurity=False)` as a
  content fingerprint, not a security primitive. The **streamed `export.tsv`**
  (text/tab-separated-values) and `no-store` health are **skipped** (never
  buffered). Alternative — a pure-ASGI middleware that taps the body without
  buffering — was more code for no real memory win here (JSONResponse already holds
  the whole body in memory).
- **nginx `proxy_cache` complements the ETag, it doesn't replace it.** A shared
  reverse-proxy micro-cache (`web/nginx.conf`, http-context `proxy_cache_path`)
  means repeat GETs across all clients skip the API and DB; `proxy_cache_revalidate
  on` turns an expired entry into a cheap upstream 304 (using the ETag) instead of
  a full re-fetch; nginx still honours the API's `Cache-Control` (so `no-store`
  health is never cached). `X-Cache-Status` is surfaced for tuning. A CDN and an
  in-process LRU remain optional future scale-ups.

## Open — still to decide

- None — the two data-model forks are resolved: **no `base_count`** (settled
  above, 2026-08-02) and the **quality-stat modelling** shipped in Stage A
  (`QualityStat` / `QUALITY_STATS` in `core/metrics.py`).
