# Migration roadmap

Staged so there is a working, demoable thing at the end of each phase. The two
open forks (DB engine, frontend framework) only need locking before the phases
that depend on them.

## Phase 0 — Decide & scaffold
- Resolve the open forks in [`../DECISIONS.md`](../DECISIONS.md).
- Monorepo layout: `pipeline/`, `api/`, `web/`, `infra/` (docker-compose), `docs/`.
- `docker-compose.yml` with Postgres + a placeholder API + web.

## Phase 1 — Data foundation (the real work)
- Load NCBI **taxdump** into `taxon`: `taxid, name, rank, parent_id, path`.
  Verify counts against the old DB (~1.8M eukaryote nodes).
- Port the **rollup** into `clade_features` (reuse Euka-Survey's logic; move the
  aggregation to DuckDB/Polars). Validate against the old numbers for known
  clades (e.g. Eukaryota 2759).
- Confirm both canonical queries run fast **without** `precomputed_taxa` and
  **without** ETE3. This proves the thesis of the redesign.

## Data refresh — port the fresh source fetches (independent of deployment)

The Phase-1 build reads per-species feature counts from Euka-Survey's old SQLite
(`../Euka-Survey/eukaryotes.db`, table `taxid_features`) — a deliberate Phase-1
**bridge**. Replace it by porting Euka-Survey's fetch steps so the counts come
fresh from source, then feed the roll-up from those instead of the SQLite:

- **Assemblies** — NCBI `datasets` CLI (`get_assemblies`; ports mostly as-is).
- **Annotations** — Annotrieve (`get_annotations`).
- **RNA-Seq (any + long-read)** — ENA (`get_reads`).

**This is independent work — NOT blocked by the CRG deployment.** It can be built
and run locally any time you want current data (e.g. before a demo). It also
*unblocks* Phase 5's scheduled rebuild, which must fetch fresh data rather than
read a frozen file. Keep the resumable-snapshot + atomic-swap discipline.

### Data-model enrichment + refresh pipeline (2026-08-02) — the elaborated plan

The above is now scoped concretely: the pipeline moves off the SQLite bridge to
fresh sources **and** the data model grows from counts-only to a **hybrid** that
captures per-record metadata (`assembly` + `annotation` tables), so the dashboard
+ breakdown have real substance. Full design in [`data-model.md`](data-model.md)
(Enriched data model) and [`../DECISIONS.md`](../DECISIONS.md) (2026-08-02).

**Coverage check [done 2026-08-02].** Sized how much of the tree lights up
(June-2026 snapshot; fractions hold): **67,659 assemblies** across 27,705 taxa,
**15,810 annotations** across 8,545 taxa, **8,238,507 RNA-Seq runs** across 37,211
taxa. Annotrieve tracks **16,905** assemblies (the *annotated* subset) — so
**assembly quality (level/N50/size/GC) covers 100%** of assemblies from the
`datasets` call, while **annotation quality (BUSCO/genes) covers ~25%** of
assemblies (~8.5k taxa: the reference-quality core, exactly our existing
annotation footprint).

**Source split:** `datasets` → all assemblies + quality fields; **Annotrieve
`api/v0`** → annotation richness (BUSCO, gene/transcript counts, source-DB, GFF
links); ENA → reads (aggregated, run counts only — no `base_count`).

- **Stage A [done 2026-08-02].** New `assembly` / `annotation` tables + the
  additive `clade_features` extension (`n_ass_*`, `n_reference`) in
  `infra/postgres/init`. `core/metrics.py`: `QualityStat` / `QUALITY_STATS` — the
  **annotation-quality** stats (BUSCO %, gene count) *parallel* to the count-based
  `METRICS` (distribution stats, no `c_/s_/p_` triple).
- **Stage B [done 2026-08-02].** `fetch_assemblies` (datasets, full per-assembly
  record), `fetch_annotations` (paginated Annotrieve `/annotations`: BUSCO + gene
  stats + GFF url), `fetch_reads` (ENA, run counts only). `snapshot.py` caches
  each source to parquet (`--refresh-sources` forces re-fetch). `rollup.py`:
  `assemble_leaf_features` combines the three sources; the fan-out carries the
  additive composition columns. `build.py` rewired off the SQLite bridge.
  **Two correctness fixes** (sparse fresh data vs the old all-species SQLite):
  `n_rows` takes the species universe from `taxon` (LEFT-join sparse features) so
  it counts ALL species; the rollup is **scoped to Eukaryota** (`root_taxid`,
  since `taxon` holds the whole NCBI tree). Rebuilt + verified: 69,703 assemblies
  / 18,475 annotations (15,409 BUSCO) / 1,881,955 clade rows; `n_rows` matches a
  direct `taxon` species count exactly. Needs a fresh volume (schema changed).
- **Stage C [done 2026-08-02].** `/taxon/{taxid}/assemblies` + `/annotations`
  (real per-record lists + deep links, paginated with a PK tiebreaker) each with
  **live distribution stats** (median genome size / contig N50; best BUSCO /
  median protein-coding genes) from one `ltree` subtree query; `/quality-config`
  (chrome from `QUALITY_STATS`). `summary`/`breakdown`/`children` gained
  `composition` (`CladeMetadata` extended; `SortColumn` picks it up). OpenAPI → TS
  regenerated; 79 tests pass (data-dependent ones relaxed to rebuild-safe
  invariants).
- **Stage D [done 2026-08-02].** The enrichment reaches the UI.
  - **Dashboard:** `QualitySection` (live BUSCO / genes / genome-size / N50 stat
    tiles + an ordinal-blue assembly-contiguity bar) and `RecordBrowser` (tabbed
    Assemblies/Annotations drill-down with real NCBI/GFF deep links, sortable,
    load-more) on every dashboard.
  - **Breakdown redesign — the click-to-drill "data map"** (default breakdown;
    standalone at `/map/:taxid`, nav "Data map"). A proportional treemap
    (`d3-hierarchy`): area = species or assemblies, colour = a lens (3 coverage +
    4 quality) on one theme-aware ramp. Big + pale = a big clade with little data
    (the gap). Clicking a tile drills to the next meaningful rank (auto-jumps past
    rankless clades, so no rank dropdown); breadcrumb climbs back. New `GET
    /clade/{taxid}/breakdown/quality?rank=R` (per-bucket BUSCO/genes/genome-size/
    N50) powers the quality lenses. **The user picked the treemap over a heatmap +
    a scatter.** Now **promoted**: the reusable `BreakdownMap` is the dashboard's
    Breakdown section (embed) and the standalone `/map` page; the old
    `BreakdownSection`/`DivergentBarChart`/`lib/breakdown` are deleted. Polished
    with a keyboard/SR list fallback, Open/Full-screen/Download-TSV actions,
    small-tile tooltips, and copy free of em dashes. Remaining niceties: URL-sync
    the drill path, true load-more past the 250-tile cap.

## Phase 2 — API
- FastAPI endpoints: `summary`, `breakdown` (filter/sort/limit pushed down),
  `taxon`/lineage (breadcrumb), `export.tsv`, name search.
- Port the `Metric` config as single source of truth; generate OpenAPI + TS types
  from it. Response caching for common clades.

## Phase 3 — Frontend: the dashboard (Q1)
- Rebuild the "Genomic Resource Summary": metric cards, total-species, coverage
  bars, Wikipedia "About" card, lineage breadcrumb, root picker.
- **[done] Wikipedia "About" card** (2026-07-31): `GET /taxon/{taxid}/about`
  proxies Wikipedia's REST summary server-side (User-Agent + caching + typed
  bridge; see `../DECISIONS.md`), returning `TaxonAbout | null`. `AboutCard`
  renders thumbnail + blurb + link on `/clade/:taxid`, decorative (omitted on
  null/error). **CSP follow-up:** allow `img-src upload.wikimedia.org` when TLS
  + CSP land, or proxy the thumbnail.

## Phase 4 — Frontend: the breakdown (Q2)
- The filter/sort/limit **table** with coverage bars, plus a bar chart.
- Downloads (displayed rows + full breakdown TSV).

## Phase 5 — Productionization

> **Deployment target — deferred (2026-07-31).** The app will be deployed on
> CRG/guigolab's (Docker-based) server once it's more functionally interesting,
> decided with Guigó + the team's IT expert. The items below that depend on the
> actual deploy environment — the scheduled rebuild run against the live DB,
> TLS, staging-vs-prod DB, gateway rate limiting — are **on hold** until then.
> Everything deploy-agnostic is already done (prod compose, healthchecks,
> secrets, CORS, response caching). See `../DECISIONS.md`.

### Deploy & runtime
- **[done]** Full Dockerized deploy: `web/Dockerfile.prod` (multi-stage —
  `node:22-slim` build → `nginx:alpine` serving the SPA + proxying `/api`) and
  `infra/docker-compose.prod.yml` (all three services containerized, container
  healthchecks, only web published). User-verified end-to-end.
- **[done]** Health checks (`/health` liveness, `/health/ready` DB) + structured
  JSON logging (`logging_config.py`, per-request middleware).
- **[done]** CI (`.github/workflows/ci.yml`): ruff lint + pytest + web
  typecheck/build; secret scan (gitleaks) + dependency audits (pip-audit, npm
  audit) + Dependabot. Also fixed 8 pre-existing repo-wide lint errors.
- **[done 2026-08-02]** CI test database: the DB-backed API tests no longer skip
  in CI. A `postgres:17` service is seeded with a compact consistent slice
  (`scripts/generate_ci_seed.py` → committed `api/tests/seed.sql`, applied by
  `scripts/load_ci_db.py`) whose `clade_features` is recomputed via the pipeline
  rollup so every aggregate is exact; the suite runs 85 tests with zero skips.
  Only one assertion changed (`test_summary.py` `n_rows` → adaptive species-count
  invariant, exact on both prod and the slice).
- Scheduled offline **dataset** rebuild (GitHub Actions cron or Nextflow) keeping
  the resumable-snapshot + atomic-swap discipline; staging vs prod DB; basic
  metrics.
  resumable-snapshot + atomic-swap discipline; staging vs prod DB; basic metrics.
- **[done]** Response caching: `Cache-Control: public, max-age=$CACHE_MAX_AGE`
  on cacheable GETs (health = `no-store`), so browsers / a CDN / a reverse proxy
  cache between rebuilds. Follow-ups: nginx `proxy_cache` or a CDN in front,
  ETag/304 conditional requests, and an in-process LRU for the hottest clades.

### Security & secrets — assistant owns this; acknowledge & fix each when reached
Credential externalization is **done** (compose reads `${POSTGRES_*:-eukahub}`,
`infra/.env.example` committed, `infra/.env` gitignored). Remaining, to action
in this phase:
- **[done] Postgres `5432` not published in prod.** `infra/docker-compose.prod.yml`
  keeps Postgres (and the API) on the internal network — only web is published
  (8080). The `5432:5432` mapping remains a local-dev convenience in the dev
  compose only.
- **Real prod credentials from a secret store** (GitHub Actions secrets / host
  env), never committed. Gotcha: Postgres applies `POSTGRES_PASSWORD` only on
  first volume init — a real password needs a fresh volume or `ALTER USER`.
- **TLS/HTTPS** terminated at a gateway / reverse proxy in front of `api` + `web`.
- **[done] CORS** — configurable allowlist via `CORS_ALLOW_ORIGINS` (FastAPI
  CORSMiddleware, GET-only, no credentials). **Rate limiting** at the gateway
  still to add.
- **[done] Auth decision:** no user auth — the API serves only public, read-only
  data; if abuse appears, add gateway rate limiting / optional API keys, not
  login. Recorded in DECISIONS.md (2026-07-31).
- **[done] Security headers**: baseline (`X-Content-Type-Options`,
  `X-Frame-Options`, `Referrer-Policy`) on API responses (middleware) and on the
  static SPA (`web/nginx.conf`, in `location /` so `/api` isn't double-set).
  **HSTS + a CSP** still to add with TLS. Plus a **dependency / secret scan** in
  CI **(done)**: gitleaks secret scan + pip-audit / npm audit + Dependabot.
- **Dependency advisories (from CI `npm audit`, non-blocking):** upgraded to the
  latest majors 2026-07-31 (react-router-dom 7, vite 8, openapi-typescript 7.13,
  @vitejs/plugin-react 6) — build + typecheck pass with **no code changes**;
  cleared the fixable ones. **6 high remain with no forward fix** (npm offers
  only downgrades): 4 in the dev-only `openapi-typescript → @redocly/openapi-core
  → minimatch/brace-expansion` chain (never shipped), and react-router-dom /
  react-router (runtime, but low practical risk — SPA does internal numeric-taxid
  nav only, no SSR). Revisit when upstream patches.

### Verify
- `docker compose config` resolves; a fresh clone comes up on dev defaults with
  no committed secret; prod overrides via `--env-file`.

## Phase 6 — Interactive Tree of Life

- **[done] Radial "Tree of Life" (2026-08-01).** The showcase piece: a radial
  dendrogram at `/tree/:taxid` that lazy-expands via a new
  `GET /taxon/{taxid}/children` endpoint (adjacency `parent_id`, sorted by
  species count, `count(*) OVER ()` total + `has_children` flag, limit/offset
  paging for the huge-fan-out nodes). Frontend: `useTree` state reducer +
  `RadialTree` (SVG, `d3-hierarchy`/`d3-shape` for layout only; node size ∝
  √species, colour = sequential assembly-coverage ramp per the dataviz skill),
  hover tooltip, click-to-expand, "load more", pan/zoom, and a keyboard/
  screen-reader **text-outline fallback** (`TreeOutline`). Cross-linked with the
  dashboard both ways. See `../DECISIONS.md` (radial form + `d3-hierarchy` dep).
- **[done 2026-08-03] In-tree search highlighting.** A "Find a group in this tree"
  box in the Tree header (`RootPicker` `onPick`): on pick, `useTree.reveal(path)`
  expands + pages each ancestor (limit 100, `REVEAL_MAX_PAGES` cap) until the
  target loads, then `RadialTree` selects it, pans it to centre, and plays a
  one-shot pulse ring (`prefers-reduced-motion` respected). Fallbacks: "not inside
  this group" (with an "Open its own tree" link) and a "buried" message past the
  cap. No API change.
- **Scale-up path (future):** a Canvas/WebGL renderer if we ever want thousands
  of nodes on screen at once — the SVG MVP is bounded by lazy-expand + a
  visible-node guardrail, so it isn't needed yet. Also future: a `child_count`
  rollup column (drop the per-row `EXISTS` probe) and animated expand/collapse
  transitions.

## Phase 7 — Layout & space-usage overhaul (done 2026-08-01)

**[done] Shipped on `dev`** (commits `7531969` layout, `15647fa` Tier-1 UX
batch). The centered `--maxw: 1100px` column is gone: the cap widened to 1360px,
the dashboard is a two-column body (sticky context rail — About + Tree CTA +
species "Get the data" — beside the metric grid + breakdown), and the Tree of
Life is full-bleed near-fullscreen (`.app__main--full`, `.tree` `min(80vh,920px)`)
with `RadialTree` measuring its container (ResizeObserver → viewBox) instead of
the old fixed 1100×760. `TreeOutline` kept. A follow-on **Tier-1 UX batch** also
landed: 2×2 metric cards, full-lineage wrapping breadcrumb (root + cellular
organisms stripped), outline-click-expand, search-by-TaxID (Eukaryota-scoped),
species external-data links, header GitHub button + dropdown (feedback / API docs
/ FAQ) + `/faq`, and a copy cleanup. Still light-only (dark mode deferred).
Original spec below.

Flagged by the user 2026-08-01. The whole app reads "almost vertical" — every
page is a centered column capped at `--maxw: 1100px`, so wide screens waste a lot
of left/right space. A dedicated pass, big enough for its own session:

- Rework the app-wide layout to use horizontal space (a wider cap, or a genuinely
  different layout — multi-column dashboard / sidebar / full-bleed sections — not
  just a stretched column). Keep it responsive (don't break narrow/mobile).
- Make the **Tree of Life near-fullscreen** (it benefits from all the space and
  this removes the wasted-side feeling there). Likely let that page escape
  `.app__main`'s max-width (full-bleed) and enlarge `.tree__svg`
  (`height: min(72vh, 720px)` today). The radial geometry constants in
  `RadialTree.tsx` (`VW/VH/FILL_R/RING`, tuned to today's container) should be
  revisited — probably measure the container instead of the fixed viewBox.
- **Keep the `TreeOutline` text-outline accessible view** when going fullscreen.
- Natural to pair with app-wide **dark mode** (still deferred).

## Backlog — user suggestions (opened 2026-08-01)

Remaining items from the user's suggestions list (the Tier-1 quick wins are done
under Phase 7 above). Each major one wants a design/scope decision before coding:

- **[done] Dark mode (2026-08-01)** — app-wide, via `data-theme` on `<html>`: a
  pre-paint inline script in `web/index.html` (no flash) + `web/src/lib/theme.ts`
  (persist + follow-OS store, `useTheme`) + a `ThemeToggle` in the header. One
  **selected** dark token block in `index.css` (not an auto-flip; `color-scheme:
  dark`), with `--cta` (button surface) split from `--link` (text) so white-on-blue
  keeps contrast, and the previously-hardcoded light surfaces (app bar, tree
  overlays, canvas-gradient centre, node outline, error text) tokenised.
  `RadialTree.tsx` re-anchors the sequential coverage ramp **dim→hue→bright** for
  the dark canvas (dark no-data neutral), tuned with the dataviz `--ordinal`
  validator (low-end ≥2:1). Categorical metric hues kept as-is (background-
  independent separation; same accepted Paired trade-off as light — relief via
  track + inset edge + table/legends). Deeper dark-specific metric hues (needs
  variants plumbed through the API config) deferred as a separate scope.
- **Breakdown redesign** (design-first) — the user dislikes the whole current
  breakdown (`BreakdownSection` + `DivergentBarChart`); bring 2–3 layout
  directions before building. **Now sequenced after the data-model enrichment**
  (2026-08-02): redesigning on top of 4 sparse count-bars just rearranges thin
  material, so it becomes **Stage D** of that plan, built on the richer columns
  (assembly quality tiers, genome size, gene counts, BUSCO).
- **[done] Landing / hero page (2026-08-01)** — user calls it **"good enough for
  now"** (parked; revisit later). `/` now renders a `Landing` hero (chosen frame:
  **clean hero + discovery**) instead of redirecting to Eukaryota: the **"EukaHub"
  name front and centre** (large solid two-tone wordmark, "Hub" in the link accent,
  no gradient, Annotrieve-style), a tagline + lede, the `RootPicker` search enlarged
  as the focal control, quick-jump "Try:" chips, a **"Surprise me with a random
  clade"** button, and the two primary journeys (Explore Eukaryota / Tree of Life).
  Data-light, nothing fetched on load. The random-clade + chip source is a curated
  pool of 32 recognizable, data-rich groups (`web/src/lib/clades.ts`), **every taxid
  verified against the live DB** so a new user never lands on an empty/obscure node.
  Reusable `RandomCladeButton` (reads the current `:taxid` so it never re-rolls the
  same group) also sits in the app bar so returning users can re-roll from any page.
  Header nav is now **EukaHub · Dashboard · Tree of Life** (brand goes to `/`; a
  Dashboard link was added, prefix-active on `/clade/`). Per house style: **no em
  dashes and no emojis** in copy or UI, so the old 🎲/🌳 became inline SVG icons
  (`web/src/components/icons.tsx`, `currentColor`) reused in the hero, the app bar,
  and the dashboard tree-link. All hero styles are token-driven so dark mode is
  automatic (light + dark screenshotted). Build + typecheck clean.
  - **[done 2026-08-02] Direction B — the live "at a glance" data strip +
    featured-group coverage cards.** New cacheable `GET /overview` (global
    eukaryotic totals + a server-defined featured list, each with assembly/
    annotation coverage; absent taxids dropped so the sliced CI DB stays robust).
    `Landing.tsx` renders a non-blocking totals strip (`fmtCompact`) + a responsive
    grid of featured-group cards (friendly label from `clades.ts`, species count,
    assembly-coverage meter, dashboard link) — the gap reads instantly (Insects
    765k species / 0.72% assembled vs Birds 17.4%). 4 slice-safe API tests; 89
    pass; light + dark screenshotted. Still-deferred polish: vertical centring in
    the viewport.
- **[done] Subspecies / infraspecific taxa (2026-08-01)** — decisions: **all
  infraspecific ranks** (subspecies, strain, varietas, forma, isolate, ...),
  **directly-attached counts**. Additive, so the core thesis is untouched: the
  species rollup stays `rank = 'species'`, and `_infraspecific_rows` (`rollup.py`)
  adds one row per below-species taxon holding **only its own** directly-attached
  features with `n_rows = 1`, never summed into any ancestor (disjoint taxids →
  plain concat). Verified: *Canis lupus* (species) shows 4 assemblies while its
  subspecies *familiaris* shows 40 — the 40 is not rolled up; a species with
  subspecies still has `n_rows == 1`. `is_infraspecific` is derived at serve time
  (`EXISTS` species-ancestor probe — no stored flag/schema change) and threaded
  through `summary` + `children`. Frontend: an infraspecific dashboard renders as
  **leaf detail** (count-mode `MetricCard`s, "Get the data" links, a "not counted
  upward" note, no coverage meter or generic breakdown); species/leaf dashboards
  gain a **"Subspecies & strains"** section (`SubspeciesSection`, via `/children`,
  sorted data-first) listing the finer taxa. DB rebuilt (validation still within
  0.3%); 63 tests pass; light+dark screenshotted. `data-model.md` updated.
- **[done] Feedback via Google Form → GitHub issue (2026-08-02)** — a public
  Google Form that files a labeled GitHub issue via an Apps Script `onFormSubmit`
  trigger, so users **without a GitHub account** can submit. **Security (assistant
  owns):** the Apps Script holds a *fine-grained* PAT (Issues: read/write on this
  repo only) in Script Properties, server-side — never in the repo, frontend, or a
  classic `repo` token; the submitter's email is kept in the private form
  responses, never printed into the public issue. The script maps the form's
  "Type of feedback" to a repo label (bug/enhancement/question) plus `feedback`.
  App wiring: header "Send feedback" opens the form (no account needed); a FAQ
  entry notes that GitHub-account users can open an issue directly. Repo also
  gained structured **issue forms** (`.github/ISSUE_TEMPLATE/` bug + idea,
  auto-labeled) and a `config.yml` contact link routing account-less users to the
  form (GitHub reads these from the default branch, so they surface once `main`
  has them). The Google account / PAT / Form live in the user's accounts
  (set up by the user with assistant-provided script + field copy).
- **[done 2026-08-03] Compare groups view** (new feature; design-first, user chose
  the **hybrid chart + table**). Cacheable `GET /compare?taxids=a,b,c` (2-6 groups)
  returns each group's species count + per-resource coverage + live quality stats
  (BUSCO / genes / genome size / N50). `ComparePage` at `/compare` (nav link): a
  grouped horizontal bar chart of coverage % (one colour per group, shared
  auto-scaled axis, value-at-tip) + a sortable numbers table; groups live in the
  URL (`?taxids=`, shareable), colour-follows-entity, chips + presets. The 6-slot
  group palette is the **dataviz** skill's validated categorical default,
  re-validated against the app surfaces. `RootPicker` gained an `onPick` callback.
  6 slice-safe API tests; suite 95 pass; light + dark + empty-state screenshotted.
- **[done 2026-08-03] Contextual cross-navigation.** The top nav
  (Dashboard/Tree/Map) is now **context-aware** (`App.tsx` derives the taxid from
  a `/clade|/map|/tree/:id` route and carries it; Compare stays multi-taxon), and
  a clade's other views are reachable from the dashboard's **sticky rail** as
  filled **CTA buttons** (`ViewSwitcher.tsx`) under the About card — canonical
  order Dashboard - Tree of Life - Data map, current omitted, Tree of Life green +
  Data map blue, plus an "Add to compare" link. The user preferred the CTA-button
  style over a segmented switcher, so the in-page control is CTA buttons (not a
  segmented switcher); the Tree page also got its intro description restored to
  full width. **Follow-up (done):** `ViewSwitcher` gained a `layout` prop and the
  CTA buttons now also appear on the **Tree + Map** pages as a compact horizontal
  **row** in the header (`layout="row"`, current view omitted, same canonical
  order), so cross-nav is in-page on all three taxon-scoped views (not just the
  dashboard rail).

Smaller follow-ups from this session:
- Verify the **API docs behind the proxy** (`/api/docs`) render with
  `root_path="/api"` once the full stack runs (couldn't test headless here).
- **[done 2026-08-03] Header wrap on narrow viewports.** The app bar now stacks
  into rows below **920px** (brand + action icons / primary nav / full-width
  search) via `flex-wrap` + `order`, staying one clean row above it (nav
  `white-space: nowrap` + `flex-shrink: 0` so the search yields, not the nav). Part
  of the responsive / mobile pass — see below.
- **[done 2026-08-03] Responsive / mobile pass.** Header wrap (above) plus a
  headless overflow audit (scrollWidth vs viewport at 320/390/480/600/768) that
  fixed two real overflows — the breakdown map's `.bmap-actions` (`flex: none`, so
  its buttons couldn't wrap; a 10px dashboard overflow) and the compare add-group
  search (`.cmp__add`, fixed 340px, overflowed at 320px) — and made the Tree
  "Colour by" segmented control `overflow-x: auto` below 560px so its clipped
  last lens ("Long-Read RNA-Seq") stays reachable. Wide data tables already sit in
  `overflow-x:auto` wrappers. Deferred polish: a scroll affordance / card layout
  for those wide tables, and landing viewport centring.
- **[done 2026-08-03] react-router audit highs — RESOLVED via the React 18 -> 19
  upgrade.** Bumped `react`/`react-dom` to `^19.2.8`, `@types` to `^19`, and
  replaced `react-router-dom@7` with `react-router@^8.3.0` (v8 merged the DOM
  bindings into `react-router`; the 16 import sites swapped
  `"react-router-dom"` -> `"react-router"`, `BrowserRouter` + all hooks still on the
  main entry). Node 24 satisfies react-router 8's `engines >= 22.22`. `npm audit`
  now reports **0 vulnerabilities**; the RSC-mode CSRF advisory
  (GHSA-qwww-vcr4-c8h2) — never reachable in our declarative SPA — is cleared with
  the actual patched version. No app-code changes beyond the import swaps (pre-scan
  found no React-19 type breakage).

## Reuse vs rebuild vs delete

| Reuse (port) | Rebuild | Delete |
|---|---|---|
| Build pipeline (Python) | Presentation (Streamlit → SPA) | ETE3 (build + runtime) |
| Rollup/aggregation logic | Data-access as an HTTP API | PyQt5 / matplotlib tree |
| `Metric` config | Taxonomy storage (into our DB) | `precomputed_taxa` + index |
| filter/sort/limit semantics | | 400 MB download model |
| Schema-version discipline | | |
| Wikipedia "About" card idea | | |
