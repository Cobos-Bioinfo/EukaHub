# CLAUDE.md — EukaHub

Resume anchor for a fresh session. Read this, then the docs below.

## What this is

A production-grade rewrite of **Euka-Survey** (a Streamlit app exploring public
genomic-data availability across the tree of life). The old app lives intact at
`../Euka-Survey` (sibling dir) — read it when porting logic.

For any user-picked taxon the app answers two questions:
1. **How much data is there?** (the "Genomic Resource Summary" dashboard)
2. **How is it distributed at a lower rank?** (breakdown: table/chart now,
   interactive Tree of Life later)

Data sources: NCBI (assemblies), Annotrieve (annotations), ENA (RNA-Seq). The
dataset is rebuilt offline on a schedule and served **read-only** — this drives
most of the design.

## Status

**Phases 0–1 complete & validated** (2026-07-29). uv workspace (`core`/`api`/
`pipeline`), `web/` Vite placeholder, `infra/docker-compose.yml` (Postgres +
`ltree`). Phase 1 loaded the taxdump into `taxon` (2.9M nodes, `ltree` paths)
and rolled leaf features up into `clade_features` (1.83M clades) with Polars —
no ETE3, no `precomputed_taxa`. Matches Euka-Survey within 0.3%; summary lookup
and worst-case (Eukaryota→phylum) breakdown both run in <1 ms server-side.

**Phase 2 (the API) — all five read endpoints done** (2026-07-30):
`summary` (Q1), `breakdown` (Q2 — descendants at a rank via one `ltree`
subtree query, filter/sort/limit pushed into SQL, `COUNT(*) OVER ()` for the
pre-limit total), `export.tsv` (full breakdown streamed via a server-side
cursor; old public TSV schema), `taxon/{taxid}` (root→node lineage via
`path @>` + `nlevel`), and `search` (name search, `pg_trgm` GIN index on
`taxon.name` — added to the schema and the live DB). Structure: pooled
`psycopg` (`api/…/db.py`), SQL in `queries.py`, Pydantic responses +
query-param enums both derived from `METRICS`. Breakdown defaults mirror
Euka-Survey (sort `n_rows`, exclude-empty, AND, top 25; ranks =
ALLOWED_RANKS). 36 end-to-end tests vs the live DB (shared `client` fixture
in `api/tests/conftest.py`).

**Phase 3 (the dashboard) — Q1 done** (2026-07-30). Typed API bridge:
`export_openapi.py` dumps `app.openapi()` → `web/src/api/openapi.json`;
`openapi-typescript` generates `schema.ts`; `openapi-fetch` client in
`client.ts` (`npm run gen` regenerates both). The React SPA renders the
Genomic Resource Summary for `/clade/:taxid` — metric cards + coverage meters
(`/metrics-config` joined to `summary`), total species, lineage breadcrumb
(`/taxon/{id}`), and a name-search root picker (`/search`). Verified via
typecheck + vite build + the Vite `/api` proxy against a live API; user
manually confirmed Q1 in a browser (2026-07-31).

**Phase 4 (the breakdown, Q2) — table done** (2026-07-31). `BreakdownSection`
renders below the Q1 cards on `/clade/:taxid` (keyed by taxid so a new root
resets controls): rank + sort + limit selects, per-resource filter chips with
an AND/OR toggle, an exclude-empty switch, and a comparison table of child taxa
with per-metric coverage meters. Sort/filter labels now come from the metric
config too — added `filter_label`/`sort_count_label`/`sort_total_label` to the
API's `MetricConfig` and regenerated the TS types, so control copy can't drift.
Two downloads: displayed rows (client-side TSV from the loaded items) and the
full breakdown (`/clade/{taxid}/export.tsv`).

**Phase 4 complete — divergent bar chart added** (2026-07-31). A Table/Chart
toggle in `BreakdownSection` drives both views from the same controls/data.
`DivergentBarChart` ports Euka-Survey's overlaid mirror bar: per taxon, left
half = assemblies+annotations (blue), right half = RNA-Seq+long-read (green),
each side's darker subset metric overlaid on its lighter base; the plotted
value is coverage % (0–100 per side). Built in HTML/CSS (no chart lib) with a
recessive gridline track, a dashed centre axis, a legend, and a per-row hover
tooltip. Exposed `side`/`overlay`/`legend_label` on the API's `MetricConfig`
(same no-drift path as the labels). Followed the **dataviz** skill: the 4 fixed
entity colors PASS CVD + normal-vision separation; the pale-hue lightness/
contrast FAILs are handled by relief (grey track + inset bar edge) + the table
view, per the validator's guidance — kept the palette rather than recolor.
Verified via typecheck + vite build + full API suite (31 passed) + curl;
**not yet screenshotted** (no headless browser), and the app is light-only so
chart dark mode is deferred with the rest. See `docs/roadmap.md`.

**Phase 5 (productionization) — in progress on `dev`** (2026-07-31). Three
slices done. (1) Observability: structured JSON logging (`logging_config.py`,
`LOG_LEVEL` env) + a per-request middleware; `/health` = liveness,
`/health/ready` = DB readiness (`SELECT 1`, 503 when unreachable). (2) Dockerized
deploy: `web/Dockerfile.prod` (multi-stage — `node:22-slim` build →
`nginx:alpine` serving the built SPA and proxying `/api`) + `web/nginx.conf`;
`infra/docker-compose.prod.yml` (project `eukahub-prod`, own volume, container
healthchecks, **only web published on 8080** — Postgres + API stay internal).
User-verified end-to-end: full stack builds, all three containers healthy,
nginx→api→db path works. (3) CORS (configurable `CORS_ALLOW_ORIGINS`, GET-only)
+ baseline security headers (nosniff / frame-DENY / referrer-policy) on API
responses and the static SPA. (4) CI (`.github/workflows/ci.yml`): ruff + pytest
+ web build, gitleaks secret scan + pip-audit / npm audit + Dependabot (and
fixed 8 pre-existing repo-wide lint errors). (5) Response caching:
`Cache-Control: public, max-age=$CACHE_MAX_AGE` on cacheable GETs, `no-store` on
health. 48 tests (42 API skip without a DB in CI); secrets externalized
(DECISIONS 2026-07-31). **Next: scheduled dataset rebuild + staging/prod DB** —
full checklist in `docs/roadmap.md`.

Run the build (Postgres up): `uv run --package eukahub-pipeline python -m
eukahub_pipeline.build` (add `--skip-download` to reuse an unpacked taxdump).
Run the API: `uv run --package eukahub-api uvicorn eukahub_api.main:app`.
Run the web app (dev, proxies `/api` → API): `cd web && npm install && npm run
dev`. Regenerate TS types after API changes: `cd web && npm run gen`.
Tests (whole workspace, DB up): `uv run pytest`.
Prod smoke test (full stack in containers, web on `:8080`; needs `sudo` here):
`docker compose -f infra/docker-compose.prod.yml up --build -d` · tear down with
`... down -v`.

**Tooling:** the `gh` CLI is installed and authenticated in this dev env — use
it for GitHub operations (CI/Actions status, PRs, issues). **Never** print, log,
or commit the user's credentials, secrets, or the auth token (no `gh auth
token`, no `--show-token`); redact anything sensitive before showing output.

**Wikipedia "About" card — done** (2026-07-31, on `dev`). First functional
work past Phase 5. `GET /taxon/{taxid}/about` proxies Wikipedia's REST summary
**server-side** (`wikipedia.py`: stdlib `urllib` + 24h in-process TTL cache;
`TaxonAbout` schema) — resolves the taxon name via `fetch_root`, returns
`TaxonAbout | null` (404 only if the taxid is unknown; `null` = no article,
cached as a normal 200). Frontend: `getAbout()` + `AboutCard` render thumbnail
+ blurb + Wikipedia link between the header and the metric cards on
`/clade/:taxid`, decorative (omitted on null/error). 5 API tests (network
monkeypatched); full suite 47 passed; web typecheck+build clean; verified live
against real Wikipedia through the SPA `/api` proxy (Metazoa→"Animal",
Eukaryota→"Eukaryote"). API-proxy rationale + the **CSP `img-src`
follow-up** (needed when TLS+CSP land) in DECISIONS.md / roadmap.md.

**Phase 6 — interactive radial "Tree of Life" — done** (2026-08-01, on `dev`).
The headline showcase. New `GET /taxon/{taxid}/children` (adjacency `parent_id`
lazy-expand: sorted by species count, `count(*) OVER ()` total + `has_children`
`EXISTS` flag, limit/offset paging for the max-47,783-child nodes; mirrors
`fetch_breakdown`). Frontend: `useTree` reducer (loaded-hierarchy state, lazy
fetch, expand/collapse/load-more, node guardrail) drives `RadialTree` — an SVG
radial dendrogram using **`d3-hierarchy`/`d3-shape` for layout math only**
(node size ∝ √species, colour = a sequential coverage ramp for a **user-picked
resource** — a "Colour by" selector — per the **dataviz** skill), with a light
hover tooltip, a **click-to-select details panel** (all 4 metrics + Expand +
"Open dashboard →"), zoom buttons + hand-rolled pan/zoom, "load more", and a
keyboard/SR **text-outline fallback** (`TreeOutline`). `/tree/:taxid` route + nav link, cross-linked with the
dashboard both ways. 52 API tests (+5 children, network-free); web
typecheck+build clean; verified live through the SPA `/api` proxy
(Eukaryota→Opisthokonta/Viridiplantae/Sar). Radial-form + `d3-hierarchy`
decisions in DECISIONS.md (2026-08-01). Still **light-only** (dark mode deferred
project-wide); Canvas/WebGL is a future scale-up path.

**Phase 7 — layout & space-usage overhaul + Tier-1 UX batch — done** (2026-08-01,
on `dev`; commits `7531969`, `15647fa`). Killed the centered `--maxw:1100px`
column: cap → 1360px, dashboard → two-column (sticky context rail beside the
metric grid + breakdown), Tree of Life → full-bleed near-fullscreen with
`RadialTree` measuring its container (ResizeObserver → viewBox) not the old fixed
1100×760; `TreeOutline` kept. Tier-1 UX batch: 2×2 metric cards, full-lineage
wrapping breadcrumb (root + cellular organisms stripped), outline-click-expand,
search-by-TaxID + name search both **Eukaryota-scoped**, species "Get the data"
links, header GitHub button + dropdown (feedback via prefilled GH issue / API
docs / FAQ) + `/faq`, plainer copy. API: `/search` scoped to Eukaryota,
`root_path="/api"` for proxied docs, Annotrieve link fixed. 58 tests pass.
Remaining suggestions (dark mode, breakdown redesign, landing page, subspecies,
Google-Form feedback) logged in `docs/roadmap.md` **Backlog**. Still light-only.

**App-wide dark mode — done** (2026-08-01, on `dev`). First Backlog item taken.
Applied via `data-theme` on `<html>`: a pre-paint inline script in `web/index.html`
(no light-flash) + `web/src/lib/theme.ts` (persist + follow-OS store, `useTheme`
hook) + a `ThemeToggle` sun/moon button in the header. `index.css` gains one
**selected** dark token block (`:root[data-theme="dark"]`, `color-scheme: dark`) —
not an auto-inversion (dataviz skill) — and splits `--cta` (button surface) from
`--link` (text) so white-on-blue keeps contrast; the previously-hardcoded light
bits (app bar, tree legend/zoom/panel overlays, radial-canvas gradient centre,
node outline, error text) become tokens. `RadialTree.tsx` re-anchors the tree's
sequential coverage ramp **dim→hue→bright** for the dark canvas (+ dark no-data
neutral); ramp tuned with the dataviz `--ordinal` validator (low-end ≥2:1). The
categorical metric hues (ColorBrewer Paired) are kept unchanged — separation is
background-independent, same accepted trade-off as light (relief via track+edge+
table/legends). Web typecheck+build clean; user-verified in a browser. Still
missing dark-mode polish is nil for now; deeper dark-specific metric hues (would
require plumbing variants through the API config) deferred as a separate scope.

**Landing / hero page — done, "good enough for now"** (2026-08-01, on `dev`).
Second Backlog item taken (design-first; user picked the **clean hero + discovery**
frame, then called the result good enough and parked it for later polish). `/` now
renders `Landing` instead of redirecting to Eukaryota: the **"EukaHub" name front
and centre** (large solid two-tone wordmark, "Hub" in the link accent, no gradient,
Annotrieve-style), a tagline + lede, the `RootPicker` search enlarged as the focal
control, quick-jump "Try:" chips, a **"Surprise me with a random clade"** button,
and the two primary journeys (Explore Eukaryota / Tree of Life). Data-light, nothing
fetched on load. Chips + the random button draw from a **curated pool of 32
recognizable, data-rich groups** (`web/src/lib/clades.ts`), **every taxid verified
against the live DB** so a first-time visitor never lands on an empty/obscure node.
Reusable `RandomCladeButton` (reads the current `:taxid` so a re-roll never repeats)
also lives in the app bar for re-rolling from any page; brand link now points at
`/`, and the header nav gained a **Dashboard** link (prefix-active on `/clade/`) so
it reads **EukaHub · Dashboard · Tree of Life**. **House style (see the
writing-style memory): no em dashes and no emojis** in copy/UI, so the old 🎲/🌳
are now inline SVG icons (`web/src/components/icons.tsx`, `currentColor`) reused in
the hero, app bar, and dashboard tree-link. All hero styles are token-driven, so
dark mode is automatic, verified via headless screenshots in **both** light and
dark. Web typecheck + build clean; no API change. Deferred polish: a live "at a
glance" data strip + featured-clade coverage cards (Direction B), viewport centring.

**Subspecies / infraspecific taxa — done** (2026-08-01, on `dev`). Third Backlog
item, the deepest (touches the pipeline rollup + the core thesis). Decisions (from
the user): **all infraspecific ranks** (subspecies, strain, varietas, forma,
isolate, ...), **directly-attached counts**. The change is **additive** and does
**not** disturb the "aggregates are species-only" thesis: the species rollup still
filters `rank = 'species'`; a new `_infraspecific_rows` pass (`pipeline/.../rollup.py`)
adds one `clade_features` row per below-species taxon holding **only its own**
directly-attached features with `n_rows = 1`, **never summed into any ancestor**
(the two row-sets have disjoint taxids, so it's a plain concat). Proof: *Canis
lupus* (species) shows 4 assemblies while its subspecies *familiaris* shows 40 —
the 40 never rolls up; a species with subspecies still has `n_rows == 1`.
`is_infraspecific` is **derived at serve time** (one indexed `EXISTS`
species-ancestor probe — no stored flag, no schema change), threaded through
`/summary` + `/children`. Frontend: an infraspecific dashboard renders as **leaf
detail** — count-mode `MetricCard`s (own record totals, no coverage meter), the
"Get the data" source links, a "not counted upward" note, and **no** generic
breakdown; species/leaf dashboards gain a **"Subspecies & strains"** section
(`SubspeciesSection`, fetched via `/children`, sorted data-first) that lists the
finer taxa, each navigable. DB **rebuilt** locally (~3 min; validation still
within 0.3% of Euka-Survey, ancestor rows unchanged); ~3,151 below-species taxa
now carry visible data (of ~73k below-species rows total). TS types regenerated;
63 tests pass (4 new); light + dark screenshotted; `docs/data-model.md` updated.

**Feedback via Google Form → GitHub issue — done** (2026-08-02, on `dev`). Fourth
Backlog item. A public Google Form files a labeled GitHub issue via a Google Apps
Script `onFormSubmit` trigger, so people **without a GitHub account** can submit.
Split: the Form / PAT / Apps Script live in the **user's** Google + GitHub accounts
(the user set them up with assistant-provided script code + exact field copy); the
repo + frontend are mine. **Security (assistant owns):** fine-grained PAT (Issues
read/write on this repo only) stored in the Apps Script's Script Properties,
server-side — never in the repo, the frontend, or a classic token; the submitter's
optional email stays in the private form responses and is **not** printed into the
public issue. The script maps the form's "Type of feedback" to a repo label
(bug/enhancement/question) + `feedback`. Frontend (`HeaderMenu.tsx`): "Send
feedback" opens the Form (no account needed); a FAQ entry notes that GitHub-account
users can open an issue directly (which surfaces the templates), and a stray em
dash was fixed. Repo also gained structured **issue forms** (`.github/ISSUE_TEMPLATE/`:
`bug_report.yml`, `idea.yml`, auto-labeled) plus `config.yml` with a contact link
routing account-less users to the Form — the applicable analog of a PR-template's
guided rules. Web build + typecheck clean.

**Data-model enrichment + refresh pipeline — planned & in progress** (2026-08-02,
on `dev`). Picked over the standalone breakdown redesign (which is now sequenced
*after* it — redesigning 4 sparse count-bars just rearranges thin material). The
pipeline moves off the Phase-1 SQLite bridge to fresh sources, and the data model
grows **counts-only → hybrid**: per-record `assembly` + `annotation` tables +
additive `clade_features` extensions; reads stay aggregated (ENA ~8.2M runs).
**Key finding:** Annotrieve (`api/v0`) already holds the assembly *and* rich
annotation metadata we'd otherwise compute — it exposes `/assemblies`,
`/annotations` (with **BUSCO**, gene/transcript counts, source-DB, direct GFF
links), taxonomy, organisms, bioprojects. **Source split:** `datasets` → all
~68k assemblies + quality fields (level/N50/genome-size/GC — 100% coverage);
**Annotrieve → annotation richness** on the annotated subset (~17k assemblies /
~8.5k taxa ≈ 25% — the reference-quality core); ENA → reads. **New
annotation-quality dimension** (BUSCO %, gene count) surfaced as headline stats +
sortable breakdown columns. Distribution stats (medians, BUSCO) are computed **on
demand** from the small per-record tables (medians aren't additive); only counts
join the rollup. Design written to `DECISIONS.md` (2026-08-02), `docs/data-model.md`
(Enriched data model), `docs/roadmap.md` (Stages A–D).

**Stages A + B DONE + DB rebuilt & verified** (2026-08-02, on `dev`, commits
`1cd01d1` `5a1dead` `8f01410` `740ccad`). Stage A: `assembly`/`annotation` tables
+ additive `clade_features` composition columns + `QualityStat`/`QUALITY_STATS` in
`core/metrics.py`. Stage B: `fetch_assemblies` (datasets), `fetch_annotations`
(Annotrieve, paginated), `fetch_reads` (ENA), `snapshot.py` (parquet source cache,
`--refresh-sources`), `assemble_leaf_features` + rollup carrying the composition
columns, `load_assembly`/`load_annotation`, `build.py` rewired off the SQLite
bridge. **Two rollup bugs fixed during the rebuild** (both from sparse fresh
fetches vs the old all-species SQLite): (1) `n_rows` now takes the species
universe from `taxon` (LEFT-join sparse features), so it counts ALL species not
just those with data; (2) the rollup is **scoped to Eukaryota** via
`root_taxid` (taxon holds the whole NCBI tree). Live rebuild (~3.5 min, snapshots
reused): **2.9M taxon, 69,703 assemblies, 18,475 annotations (15,409 with BUSCO),
1,881,955 clade_features**; `n_rows` matches a direct `taxon` species count
exactly; composition level-split sums to `s_ass`. 17 pipeline tests pass. Rebuild
needs a fresh volume (`sudo docker compose -f infra/docker-compose.yml down -v &&
up -d db`) then `uv run --package eukahub-pipeline python -m eukahub_pipeline.build
--skip-download`.

**Stage C DONE** (2026-08-02, on `dev`, commit `901e66d`). The enrichment reaches
the API. New: `GET /taxon/{taxid}/assemblies` + `/annotations` (real per-record
lists with deep links, paginated, PK tiebreaker for stable paging) each carrying
**live distribution stats** (median genome size / contig N50; best BUSCO / median
protein-coding genes) computed from the per-record tables via one `ltree` subtree
query; `GET /quality-config` (chrome for the quality dimension, analogue of
`/metrics-config`, from `QUALITY_STATS`). `summary`/`breakdown`/`children` now
carry `composition` (assembly-level split + reference count) — `CladeMetadata`
gained the additive columns, so `SortColumn` sorts by them too. dict_row +
field-aliased SELECTs; stats built config-driven from `QUALITY_STATS`. OpenAPI +
TS regenerated; web typecheck+build clean; 79 tests pass (data-dependent tests
relaxed to rebuild-safe invariants). **Next: Stage D** — the frontend: annotation-
quality cards + genome-size/N50 on the dashboard, per-record "Get the data"
deep-link lists (from the two new endpoints), then the **breakdown redesign**
(design-first, 2-3 directions). The web app still renders the old 4-metric shape
until Stage D lands.

## Read before doing anything

- `docs/data-model.md` — **the core doc.** DB design + taxonomy-tree storage.
- `docs/architecture.md` — target stack and how it maps to the deploy host.
- `docs/roadmap.md` — the staged plan.
- `DECISIONS.md` — every settled decision and the few still open.
- `README.md` — overview + status.

## Settled stack (why in DECISIONS.md)

- **DB:** PostgreSQL. Taxonomy = `parent_id` (adjacency) + `ltree` lineage.
  Feature rollups kept from Euka-Survey.
- **Backend:** FastAPI (Python), REST + auto-OpenAPI. Reuse old domain logic.
- **Frontend:** React + TypeScript (Vite + React Router SPA).
- **Packaging:** Docker + docker-compose. Python deps via **uv** (workspace).
- **Pipeline:** Python; taxonomy from NCBI taxdump; assemblies via the NCBI
  `datasets` CLI (installed in the dev env); rollup via DuckDB/Polars.

## Non-negotiables (don't reintroduce the old pain)

- **No ETE3** (build or runtime). Taxonomy lives in Postgres.
- **No `precomputed_taxa`-style cache.** The breakdown is one indexed `ltree`
  query for any root.
- **Serving is read-only;** rebuilt offline. Denormalize freely.

## Immediate next step (pivot to functional work)

Phases 0–4 done; **Phase 5's deploy-agnostic work is shipped on `dev`** (logging
+ health, secrets, Dockerized deploy, no public `5432`, CORS + headers, CI +
secret/dep scan, response caching, auth decision). **Deployment is deferred**
(DECISIONS.md, 2026-07-31): it happens on CRG/guigolab's server, decided with
Guigó + the team's IT expert, once the app is more functionally interesting — so
the remaining Phase 5 items depend on CRG's env and are **on hold** (scheduled
rebuild vs. the live DB, TLS, staging/prod DB, rate limiting).

**So the next focus is functional** — the gate the user set for deploying. Done
since: the **Wikipedia "About" card**, **Phase 6 — the radial Tree of Life**,
**Phase 7 — the layout overhaul + Tier-1 UX batch**, **app-wide dark mode**, the
**landing / hero page**, **subspecies / infraspecific taxa**, and **feedback via
Google Form → GitHub issue** (see Status).

**In flight: the data-model enrichment + refresh pipeline** (see the Status entry
above and `docs/roadmap.md` "Data-model enrichment"). Chosen with the user
2026-08-02; the **breakdown redesign folds into it as Stage D**. **Stages A + B
are done and the DB is rebuilt + verified** (see the Status entry). **Resume at
Stage C** — the API: add per-record drill-down endpoints
(`/taxon/{taxid}/assemblies`, `/annotations`) returning real records + deep links
+ live distribution stats (median N50 / genome size / gene count, best BUSCO)
computed from the per-record tables; widen `summary`/`breakdown` with the
composition columns + the `QUALITY_STATS` dimension; regenerate the OpenAPI → TS
types. Then Stage D (dashboard quality cards + per-record deep-link lists +
breakdown redesign). The API + web code is untouched so far, so the live app
still renders the old 4-metric shape until Stage C/D land.

Tracked non-functional follow-ups (do when relevant): frontend deps on latest
majors — **npm audit now shows 2 highs** (react-router runtime, low practical
risk; the dev-only openapi-typescript chain cleared upstream); seed a **small CI
database** so the API tests run in CI, and caching layers (nginx `proxy_cache`/CDN,
ETag/304). **A headless browser IS available** in the dev env via
`google-chrome-stable` — use it to screenshot/verify UI changes (this note
supersedes earlier "no headless browser" remarks).

## Still open

Nothing — all forks resolved. Rollup engine settled on **Polars** at Phase 1
(DuckDB remains a viable alternative). See DECISIONS.md.
