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
- **[done]** CI (`.github/workflows/ci.yml`): ruff lint + pytest (pipeline/core;
  the DB-backed API tests skip without a seeded DB — follow-up) + web
  typecheck/build; secret scan (gitleaks) + dependency audits (pip-audit, npm
  audit) + Dependabot. Also fixed 8 pre-existing repo-wide lint errors.
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
- **Scale-up path (future):** a Canvas/WebGL renderer if we ever want thousands
  of nodes on screen at once — the SVG MVP is bounded by lazy-expand + a
  visible-node guardrail, so it isn't needed yet. Also future: a `child_count`
  rollup column (drop the per-row `EXISTS` probe), in-tree search highlighting,
  animated expand/collapse transitions.

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
  directions before building.
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
  automatic (light + dark screenshotted). Build + typecheck clean. Future polish
  (deferred): the live "at a glance" data strip + featured-clade coverage cards
  (Direction B) and vertical centring in the viewport.
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
- **Feedback via Google Form → GitHub issue** (so users without a GH account can
  submit) — Google Apps Script `onFormSubmit` POSTs to the GitHub Issues API (per
  the user's [article](https://medium.com/@01010111/using-google-forms-to-submit-github-issues-efdb5f876b)).
  **Security (assistant owns):** use a *fine-grained* PAT scoped to Issues on this
  repo only, stored server-side in the Apps Script — never a classic `repo`-scoped
  token. Complements today's prefilled-issue link.

Smaller follow-ups from this session:
- Verify the **API docs behind the proxy** (`/api/docs`) render with
  `root_path="/api"` once the full stack runs (couldn't test headless here).
- The header isn't wrap-friendly on very narrow viewports (desktop-first today).

## Reuse vs rebuild vs delete

| Reuse (port) | Rebuild | Delete |
|---|---|---|
| Build pipeline (Python) | Presentation (Streamlit → SPA) | ETE3 (build + runtime) |
| Rollup/aggregation logic | Data-access as an HTTP API | PyQt5 / matplotlib tree |
| `Metric` config | Taxonomy storage (into our DB) | `precomputed_taxa` + index |
| filter/sort/limit semantics | | 400 MB download model |
| Schema-version discipline | | |
| Wikipedia "About" card idea | | |
