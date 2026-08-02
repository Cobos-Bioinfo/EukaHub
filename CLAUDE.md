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

**Stage D DONE — dashboard enrichment + the breakdown redesign ("data map")**
(2026-08-02, on `dev`, commits `31033fa` `467ac8f` `b1f9d8c`). The enrichment
reaches the UI. **Dashboard:** `QualitySection` (live BUSCO / protein-coding
genes / genome size / contig N50 stat tiles from the Stage-C `/assemblies` +
`/annotations` stats, plus an ordinal-blue assembly-contiguity bar with legend +
reference count) and `RecordBrowser` (tabbed Assemblies/Annotations drill-down,
real NCBI/GFF deep links, sortable, load-more paging) render on every dashboard;
`fmtBp`/`fmtQuality` helpers. One bug fixed: the record browser now clears rows
synchronously on tab/sort change so a stale assembly row never reaches the
annotation table. **Breakdown redesign — the click-to-drill "data map"** at
`/lab/breakdown/:taxid` (nav "Data map (beta)"): a proportional treemap
(`d3-hierarchy`) of a clade's subgroups — **area** = species or assemblies,
**colour** = a lens on one theme-aware sequential ramp (`lib/ramp.ts`, dataviz).
Big + pale = a big clade with little data (the gap). **Click a tile to drill to
the next meaningful rank** (auto-jumps past intermediate rankless clades — no
rank dropdown; the old five dropdowns are gone); breadcrumb climbs back. Seven
lenses: 3 coverage (assembly/annotation/RNA-Seq %) + 4 quality (contiguity %,
BUSCO, median genes, median genome size); the two magnitude lenses normalise to
the largest tile in view. Rich hover card (full coverage + quality + reference
count). **New API:** `GET /clade/{taxid}/breakdown/quality?rank=R` — per-bucket
distribution stats via one grouped `ltree` query per source (each record
attributed to its rank-R ancestor), config-driven from `QUALITY_STATS`,
`BucketQuality` schema; the map fetches it async so tiles paint instantly. **The
user chose the treemap** over a heatmap + a scatter (design-first; DECISIONS
2026-08-02) and called it "fun, interactive, truly a dashboard". 85 tests pass
(+6 breakdown-quality); web build+typecheck clean; light+dark screenshotted.

**Data map promoted + polished** (2026-08-02, on `dev`, commit `8ffb026`). The
map is now the **default breakdown**, not a beta side-route. Extracted into a
reusable `BreakdownMap` (seeded from a root ref, no lineage fetch): the dashboard
embeds it as the **Breakdown** section (`variant="embed"`, ~460–520px, with a
"Full screen" link), and the standalone page moved to **`/map/:taxid`** (nav "Data
map", **beta label dropped**, `variant="page"`, tall). The old
`BreakdownSection`/`DivergentBarChart`/`lib/breakdown` are **deleted** (JS bundle
−8 kB). Polish: a keyboard/SR **"View as a list"** fallback (every subgroup with
its numbers + drill/open links), per-clade **Open <clade> / Full screen / Download
TSV** actions, small-tile **title tooltips**, a capped-count note past the
250-tile limit, and **copy cleaned of em dashes** (house style; the user asked to
avoid AI-writing tells). Verified: build clean, light+dark + list-view
screenshotted.

**Data-map clade-rank fix + colour/gradient refinement** (2026-08-02, on `dev`,
commit `d7af73e`). Three follow-ups the user flagged on the data map. (1) **Rankless
clade bug** (was tracked in memory): a `clade`/`no rank` focus (Eutheria,
Bilateria, Opisthokonta, ...) broke the breakdown with "No phyla to map..." because
`nextRank("clade")` fell through to phylum, which is empty below a clade like
Eutheria. Fix: `targetRankFor` picks the rank from the **deepest canonical-ranked
ancestor** in the focus's lineage (Eutheria → class Mammalia → **order**; a clade
above phylum still resolves to phylum). The root lineage is threaded into
`BreakdownMap` from both callers (`Dashboard`, `BreakdownPage`); drilled tiles are
always canonical ranks so they're unaffected. (2) **Gradient direction unified**:
the sequential ramp (`lib/ramp.ts` for the map, `RadialTree` for the tree) now runs
**light→deep in both themes** (was dim→bright on the dark canvas), so "more ink =
more" and "big pale tiles are the gaps" hold in light and dark alike; the treemap
ramp's high end is deepened for readable range from pale hues. (3) **Per-lens
colours** (dataviz skill, user picked the scheme): coverage lenses take their
resource colour family (assemblies/annotations blue, RNA-Seq green — the two pale
card tints saturated so they fill a treemap), the four quality lenses share one
**purple** so "quality" reads as one dimension; only one lens is on screen at a
time. The genes lens is now explicitly **protein-coding** (button "Coding genes",
legend/list "Protein-coding genes"). Web build+typecheck clean; light+dark
screenshotted across lenses; no API change.

**Data-map drill path URL-synced + a duplicate-key fix** (2026-08-02, on `dev`,
commit `1839a5b`). The first "remaining data-map nicety" from the resume list.
The standalone map (`/map/:taxid`) now mirrors the drill trail to the URL as
`?d=t1-t2-t3` (the taxids drilled below the root), so the **browser back/forward
buttons walk the drill** and a drilled view is a **shareable, bookmarkable deep
link**. A fresh deep-link load resolves the drilled nodes' names/ranks with **one
lineage fetch of the focus** (each drilled node is an ancestor of it, so a single
`getLineage` covers them); in-session drills carry the name/rank straight from the
clicked tile, so no extra fetch. Deliberately **not** re-rooting the route (keeps
the internal drill breadcrumb, which auto-jumps rankless ranks, rather than the
taxonomic lineage). The **embedded** dashboard map keeps its internal-state trail
so it never clutters the dashboard URL; all encapsulated in a `useDrillTrail`
hook (`variant==="page"` ⇒ URL, else state). Also fixed a **pre-existing**
duplicate-key warning: `Dashboard` rendered `BreakdownMap`/`SubspeciesSection`/
`RecordBrowser` as siblings all keyed `key={taxid}`, colliding whenever a
data-rich clade shows the map + records together; the remount keys are now
namespaced (`bmap-`/`subsp-`/`rec-`). Build clean; deep-link reconstruction +
clean console verified via headless Chrome (Eutheria→Carnivora→Felidae).

**Breakdown/quality perf + the "load more" decision** (2026-08-02, on `dev`,
commit `c86f8b5`). Cleared the last two data-map niceties. (1) **"Load more" past
the 250-tile cap: decided NOT to build it.** A breakdown exceeds 250 in only ~0.5%
of clades (603 of 105k genera, 61 of 11k families, Eukaryota→phylum is 79), and a
treemap can't legibly show >250 tiles anyway (they become slivers); the full data
is already one click away (Download TSV streams the complete breakdown) and
drilling reduces the count. So the cap stays. (2) **`breakdown/quality` ~3x
faster.** It matched every per-record row to its rank-R ancestor via ltree
containment, so Eukaryota→phylum ran a 69,703×79 nested loop (~5.4M filtered
comparisons) per source (~1.2s). Now a CTE resolves each *distinct* record-bearing
taxon to its bucket once, then the records join back for the stats — same output
(21 targeted + full 68-test suite green), work scales with distinct taxa (~29k)
not records (~88k). Live: Eukaryota→phylum **1.19s → 0.39s**. Repeat hits were
already covered by the `Cache-Control` browser cache; this fixes the first hit.

**Breakdown rank-legibility: the "level" bar** (2026-08-02, on `dev`, commit
`bce9dd7`). The current position's rank was a tiny badge in the drill trail and
the tile rank was hover-only + small foot text, so "what rank am I at / what am I
looking at" took prior knowledge. Added an always-visible `bmap-level` bar under
the trail that states both as prominent rank badges: **"Viewing {focus} [RANK] →
broken down by [TILE RANK] · N groups"** (tile rank in the accent colour). Trimmed
the subtitle to the size/colour encoding, and the single-node drill trail is now
hidden at the root (the level bar names it; the trail reappears as a clickable
path once you drill). Standalone map + dashboard embed; light+dark screenshotted.

**CI test database — done** (2026-08-02, on `dev`). The ~42 DB-backed API tests
used to *skip* in CI (the `client` fixture skips when Postgres is unreachable),
so API/query regressions went uncaught. Now CI runs a `postgres:17` service
seeded with a **compact consistent slice** and the tests run against it (68 API
+ 17 pipeline/core = **85, zero skips**). Pieces: (1) `scripts/generate_ci_seed.py`
— a one-off generator (run locally vs the full DB) that picks a taxon slice
(ancestor-closure of ~10 anchor species so every lineage + `parent_id` chain is
complete; Eukaryota's 21 real direct children for the tree/children tests; a
minimal Bacteria→E. coli branch for the search-scope test), pulls real
`assembly`/`annotation` records (capped: human 120 assemblies / 20 annotations
so the record tests' `>100`/`>10` hold while the file stays tiny), reconstructs
per-species reads from the prod rollup, and **recomputes `clade_features` for the
slice via the pipeline's own rollup scoped to Eukaryota** — so `n_rows` and every
aggregate are exact and self-consistent with the seeded records. (2)
`api/tests/seed.sql` — the committed ~104 KB output (118 taxa / 88 clade rows /
232 assemblies / 69 annotations). (3) `scripts/load_ci_db.py` — applies
`infra/postgres/init/*.sql` + the seed to any `DATABASE_URL` (used by CI and
handy locally). (4) CI (`.github/workflows/ci.yml`): the `python` job gains the
Postgres service + a "Load CI test database" step + `DATABASE_URL`. **Only one
test changed** (as planned): `test_summary.py:34`'s `n_rows > 1_000_000` magic
pin became adaptive — `n_rows == (count of rank='species' under 2759)`, a
stronger invariant that holds on **both** the full prod DB and the slice. All
other DB-backed tests were already rebuild-safe (relational invariants), so they
passed on the slice unchanged. Verified: full suite green on the slice **and** on
prod; seed regenerates deterministically; ruff clean repo-wide. Re-run the
generator only when the schema or needed taxids change.

**Landing "at a glance" data strip + featured groups — done** (2026-08-02, on
`dev`). First functional feature toward the deploy gate after the CI-DB work; the
landing page's deferred **Direction B**. New `GET /overview` (one cacheable
request): global eukaryotic totals (species / assemblies / annotations / RNA-Seq /
long-read / reference genomes, from Eukaryota's rollup) + a server-defined list of
**featured groups** (`FEATURED_TAXIDS` = Mammals, Birds, Ray-finned fishes,
Insects, Fungi, Flowering plants) each with species count + assembly/annotation
coverage %. A featured taxid absent from `clade_features` is dropped (so the
sliced CI DB and any rebuild stay robust). `Overview`/`OverviewTotals`/
`FeaturedClade` schemas, OpenAPI→TS regenerated, `getOverview()` bridge. Frontend:
`Landing.tsx` renders — **non-blocking, decorative** (hero paints instantly, the
block is absent while loading / on error) — an at-a-glance totals strip
(`fmtCompact`: 1.7M / 65.4K / 16.6K / 8.2M) and a responsive grid of
featured-group cards (friendly label via `cladeLabel()` from `clades.ts`, species
count, an assembly-coverage meter, link into the dashboard). The gap reads at a
glance: Insects 765,732 species but **0.72% assembled** vs Birds 17.4%. All CSS
token-driven, so dark mode is automatic; **light + dark screenshotted** via
headless Chrome. 4 slice-safe API tests (totals cross-checked against
`/clade/2759/summary`; Mammalia the stable featured anchor); full suite **89
passed**; web typecheck+build clean; house style kept (no em dashes / emojis).
A follow-up `refine(web)` pass then dropped the "Try:" chips, made all three hero
CTAs filled distinct-hue buttons (Explore blue / Tree green / Surprise violet, all
white-text contrast-checked), and added the annotation-coverage meter to each
featured card.

**Compare groups view — done** (2026-08-03, on `dev`). The user's chosen next
feature (design-first: they picked the **hybrid chart + table** over bars-only /
table-only / side-by-side cards). New cacheable `GET /compare?taxids=a,b,c` (2-6
groups; unknown taxids dropped, deduped, capped): each group's species count +
per-resource coverage + live quality stats (BUSCO / genes / genome size / N50),
reusing `fetch_summary` + `_fetch_quality_stats` per taxid. `Compare`/`CompareGroup`
schemas; OpenAPI→TS regenerated; `getCompare()` bridge; `RootPicker` generalized
with an optional `onPick` callback (default still navigates). Frontend
`ComparePage` at **`/compare`** (nav link added): a **grouped horizontal bar
chart** of coverage % (grouped by resource, one colour per group) built in
HTML/CSS on a shared auto-scaled % axis with gridlines + value-at-tip labels, plus
a **sortable numbers table** (species, the 4 coverage %s, BUSCO/genes/genome/N50).
Groups live in the **URL** (`?taxids=`), so a comparison is shareable/bookmarkable;
colour-follows-entity (a stable slot map, so removing a group never repaints the
survivors); chips with remove, an empty-state with one-click presets. **dataviz
skill followed**: the 6-slot categorical group palette is the skill's validated
default, re-validated against the app's own card surfaces (light: PASS with the
documented 3-slot contrast WARN, covered by the table + bar labels per the relief
rule; dark: PASS all). 6 slice-safe API tests (cross-checked vs `/summary`; unknown
drop; dedupe/cap; 422s); full suite **95 passed**; web typecheck+build clean; light
+ dark + empty-state screenshotted. **Next: #3 in-tree search highlight on the
radial Tree of Life** (reuses this multi-taxon picker groundwork).

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

**The data-model enrichment + refresh pipeline is DONE through Stage D** (Stages
A–D; see the Status entries and `docs/roadmap.md` "Data-model enrichment"). The
pipeline reads fresh sources (no SQLite bridge), the API serves the per-record
drill-down + quality dimension, and the UI surfaces both: dashboard quality cards
+ record browser, and the **click-to-drill "data map"** breakdown redesign (the
user's chosen direction, live on `/lab/breakdown/:taxid` behind a beta nav link).

**Resume here.** Stage D is done and the data map is promoted + polished (see the
Status entries above). The three data-map niceties from this list are now all
resolved: **URL-sync the drill path** (done, commit `1839a5b`), **"load more" past
the 250-tile cap** (decided against — a treemap can't show >250 legibly and TSV
has the full data; commit `c86f8b5`), and the **`breakdown/quality` latency**
(optimised ~3x, `1.19s → 0.39s`, commit `c86f8b5`). Also shipped this session:
the **rankless-clade breakdown fix**, the **light→deep gradient unification +
per-lens coverage/quality colours**, a **duplicate-key fix**, and the **breakdown
"level" bar** (rank legibility, commit `bce9dd7`).

**CI test database — DONE** (2026-08-02, on `dev`; see the "CI test database"
status entry above). The ~42 DB-backed API tests now run in CI against a
`postgres:17` service seeded with a compact consistent slice
(`scripts/generate_ci_seed.py` → `api/tests/seed.sql`, loaded by
`scripts/load_ci_db.py`); 85 tests, zero skips. Exactly one assertion changed
(`test_summary.py:34` → adaptive species-count invariant). Verified green on the
slice **and** prod.

**NEXT: #3 in-tree search highlight** (planned, not started) — on the radial Tree
of Life, let the user search a taxon and highlight/pan to it. Reuses the
multi-taxon picker groundwork from the Compare view (`RootPicker`'s `onPick`).
Then: (a) more functional polish toward the deploy gate (landing viewport centring;
deeper featured-group storytelling); (b) the remaining enrichment tail; (c) Phase-5
deploy items (still gated on CRG); (d) the smaller non-functional follow-ups below.
Also a tiny CI-hygiene item: bump `actions/checkout@v4` + `gitleaks-action@v2` off
deprecated Node 20.

Tracked non-functional follow-ups (do when relevant): frontend deps on latest
majors — **npm audit now shows 2 highs** (react-router runtime, low practical
risk; the dev-only openapi-typescript chain cleared upstream); and caching layers
(nginx `proxy_cache`/CDN, ETag/304). **A headless browser IS available** in the
dev env via
`google-chrome-stable` — use it to screenshot/verify UI changes (this note
supersedes earlier "no headless browser" remarks).

## Still open

Nothing — all forks resolved. Rollup engine settled on **Polars** at Phase 1
(DuckDB remains a viable alternative). See DECISIONS.md.
