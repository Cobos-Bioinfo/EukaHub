# Graph Report - EukaHub  (2026-10-01)

## Corpus Check
- 112 files · ~79,255 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1151 nodes · 2098 edges · 71 communities (64 shown, 7 thin omitted)
- Extraction: 90% EXTRACTED · 10% INFERRED · 0% AMBIGUOUS · INFERRED: 207 edges (avg confidence: 0.68)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `04b569d1`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- queries.py
- rollup.py
- Metric
- test_auto_refresh.py
- RadialTree.tsx
- test_fetch.py
- clade_breakdown
- restore_snapshot.py
- test_limits.py
- queries.ts
- BreakdownMap.tsx
- App.tsx
- devDependencies
- fmt
- CladeMetadata
- placeholders.py
- main.py
- compilerOptions
- test_caching.py
- test_gaps.py
- RecordBrowser.tsx
- test_compare.py
- test_summary.py
- main
- load.py
- Landing.tsx
- test_breakdown.py
- taxdump.py
- GapsPage.tsx
- test_children.py
- test_taxdump.py
- Dashboard.tsx
- ComparePage.tsx
- compilerOptions
- logging_config.py
- test_search.py
- Deployment and operations
- db.py
- metrics.py
- test_records.py
- test_restore_snapshot.py
- EukaHub
- test_breakdown_quality.py
- test_overview.py
- Data model
- test_export.py
- CLAUDE.md
- schema.ts
- cached_frame
- database_url
- Contributing to EukaHub
- Design decisions
- metrics_config
- test_security.py
- Architecture
- fetch_reads.py
- conftest.py
- test_lineage.py
- lowmem-test.sh
- get_conn
- overview
- quality_config
- test_health.py
- test_meta.py
- eukahub
- dataset_summary.py
- load_ci_db.py

## God Nodes (most connected - your core abstractions)
1. `CladeMetadata` - 43 edges
2. `fmt()` - 36 edges
3. `Metric` - 32 edges
4. `QualityStat` - 28 edges
5. `main()` - 27 edges
6. `fmtPct()` - 25 edges
7. `useAsync()` - 23 edges
8. `compilerOptions` - 18 edges
9. `BreakdownMap()` - 17 edges
10. `unwrap()` - 16 edges

## Surprising Connections (you probably didn't know these)
- `FilterLogic` --uses--> `CladeMetadata`  [INFERRED]
  api/src/eukahub_api/queries.py → core/src/eukahub_core/metrics.py
- `TaxonNotFound` --uses--> `CladeMetadata`  [INFERRED]
  api/src/eukahub_api/queries.py → core/src/eukahub_core/metrics.py
- `MetricConfig` --uses--> `CladeMetadata`  [INFERRED]
  api/src/eukahub_api/schemas.py → core/src/eukahub_core/metrics.py
- `ResourceSummary` --uses--> `Metric`  [INFERRED]
  api/src/eukahub_api/schemas.py → core/src/eukahub_core/metrics.py
- `ResourceSummary` --uses--> `QualityStat`  [INFERRED]
  api/src/eukahub_api/schemas.py → core/src/eukahub_core/metrics.py

## Import Cycles
- None detected.

## Communities (71 total, 7 thin omitted)

### Community 0 - "queries.py"
Cohesion: 0.06
Nodes (57): _breakdown_where(), fetch_annotation_records(), fetch_assembly_records(), fetch_breakdown(), fetch_breakdown_quality(), fetch_children(), fetch_compare(), fetch_dataset_meta() (+49 more)

### Community 1 - "rollup.py"
Cohesion: 0.06
Nodes (54): clade_feature_columns(), The integer feature columns of ``clade_features`` in METRICS order.      Single, LazyFrame, _ancestors(), assemble_leaf_features(), carrying_taxids(), _collect(), DataFrame (+46 more)

### Community 2 - "Metric"
Cohesion: 0.09
Nodes (44): AnnotationList, AnnotationRecord, AssemblyList, AssemblyRecord, Breakdown, BucketQuality, Compare, CompareGroup (+36 more)

### Community 3 - "test_auto_refresh.py"
Cohesion: 0.07
Nodes (40): Counter, date, NamedTuple, _failing_restore(), Exception, Unit tests for the refresher's "is there newer data?" decision.  The network and, A crash would restart the container and retry the same Release immediately., A stray release (a code tag, say) must not be mistaken for a dataset. (+32 more)

### Community 4 - "RadialTree.tsx"
Cohesion: 0.08
Nodes (39): getSummary(), TaxonNode, BLACK, buildRamp(), buildVisible(), coverageColor(), Datum, hexRgb() (+31 more)

### Community 5 - "test_fetch.py"
Cohesion: 0.07
Nodes (38): fetch_annotations(), _get_report(), parse_report_row(), Fetch per-annotation records from Annotrieve (genome.crg.es/annotrieve).  Replac, The TSV report of every annotation, retried with backoff on transient errors., Download Annotrieve's annotation report and yield normalized rows.      Raises `, Cast to int (the report is text). None on failure., Normalize one row of the report into an ``annotation`` row.      Returns ``None` (+30 more)

### Community 6 - "clade_breakdown"
Cohesion: 0.09
Nodes (41): AnnotationList, clade_breakdown(), clade_breakdown_quality(), clade_export(), compare(), gaps(), meta(), Dataset provenance for the "Data updated" stamp: when the served dataset was (+33 more)

### Community 7 - "restore_snapshot.py"
Cohesion: 0.12
Nodes (36): check_invariants(), DataValidationError, _new(), _old(), Connection, Post-build validation: hard invariant gates + an optional parity printout.  Two, Gate the build on the invariants, then print the Euka-Survey parity table     wh, Raised when a post-build invariant fails — the rebuild is not shippable. (+28 more)

### Community 8 - "test_limits.py"
Cohesion: 0.07
Nodes (32): main(), Dump the API's OpenAPI schema to a file (or stdout) without a server or DB., TaxonAbout, A Wikipedia "About" summary for the taxon — the decorative dashboard card., taxon_about(), fetch_about(), _lookup(), TaxonAbout (+24 more)

### Community 9 - "queries.ts"
Cohesion: 0.12
Nodes (30): AnnotationParams, AssemblyParams, BreakdownParams, ChildrenParams, GapsParams, AnnotationList, AnnotationSort, AssemblyList (+22 more)

### Community 10 - "BreakdownMap.tsx"
Cohesion: 0.10
Nodes (30): exportTsvUrl(), CladeSummary, ALLOWED, BreakdownMap(), BucketStats, contiguityPct(), COVERAGE_HUES, COVERAGE_LENSES (+22 more)

### Community 11 - "App.tsx"
Cohesion: 0.11
Nodes (19): getLineage(), getMeta(), getMetricsConfig(), searchTaxa(), DataUpdated(), useDrillTrail(), RandomIcon(), RootPicker() (+11 more)

### Community 12 - "devDependencies"
Cohesion: 0.07
Nodes (28): dependencies, d3-hierarchy, d3-shape, openapi-fetch, react, react-dom, react-router, devDependencies (+20 more)

### Community 13 - "fmt"
Cohesion: 0.17
Nodes (24): AssemblyComposition, CovRow(), TileList(), TileTooltip(), GapsScatter(), M, niceCeil(), CompositionBar() (+16 more)

### Community 14 - "CladeMetadata"
Cohesion: 0.11
Nodes (20): clade_summary(), Genomic Resource Summary for one taxon: species count + per-resource     coverag, fetch_overview(), fetch_summary(), Return ``(name, rank, metadata, is_infraspecific)`` for one taxon.      Raises `, Landing-page "at a glance" data in one request.      Returns ``(eukaryota_metada, AssemblyComposition, CladeSummary (+12 more)

### Community 15 - "placeholders.py"
Cohesion: 0.12
Nodes (23): Rank vocabulary shared by the pipeline and the API., is_informal_species_name(), is_placeholder_name(), orphans_below_species(), prune_placeholders(), PruneStats, Placeholder taxa: species-rank names that are not formal species, and the contai, Drop placeholder taxa without data and relabel informal species that have data. (+15 more)

### Community 16 - "main.py"
Cohesion: 0.11
Nodes (22): add_response_headers(), _etag_of(), health(), _if_none_match(), log_requests(), pool_exhausted(), Request, query_timed_out() (+14 more)

### Community 17 - "compilerOptions"
Cohesion: 0.10
Nodes (20): compilerOptions, allowImportingTsExtensions, isolatedModules, jsx, lib, module, moduleDetection, moduleResolution (+12 more)

### Community 18 - "test_caching.py"
Cohesion: 0.11
Nodes (11): Cache-Control on GET responses: cacheable data endpoints, uncached health.  The, A cacheable JSON GET advertises a (weak) ETag over its body., Revalidating with the current ETag yields a bodyless 304 that keeps the     ETag, A non-matching ETag serves the full 200 body (normal cache miss)., The ETag is a stable content fingerprint: identical requests share it., The streamed TSV export is not buffered/fingerprinted (only JSON is)., test_etag_matches_across_identical_requests(), test_json_get_has_etag() (+3 more)

### Community 19 - "test_gaps.py"
Cohesion: 0.12
Nodes (14): Tests for GET /gaps — the biggest under-sequenced groups ("Where are the gaps?"), The lightweight path (used by the landing teaser) returns empty stats., A gap clade's quality stats are the same live distribution stats the     per-rec, Default call: Eukaryota, order level, assemblies. Shape + per-item     invariant, A rank/resource with a gap on both the slice and prod returns a sorted,     all-, Each ranked item is the same rollup the summary endpoint serves, and the     gap, By default each item carries the quality of the data it *does* have: one     ent, _stats_dict() (+6 more)

### Community 20 - "RecordBrowser.tsx"
Cohesion: 0.15
Nodes (13): getAnnotations(), getAssemblies(), AnnotationRecord, AssemblyRecord, QualitySection(), ANNOTATION_SORTS, ASSEMBLY_SORTS, AssemblyTable() (+5 more)

### Community 21 - "test_compare.py"
Cohesion: 0.13
Nodes (11): _parse_taxids(), The distinct taxids in a comma-separated list, in order, at most     ``_COMPARE_, Tests for GET /compare — several groups lined up side by side.  Rebuild/slice-sa, A compare entry is the same rollup the summary endpoint serves., Duplicates collapse; the response is capped at six groups., Unicode digits and absurdly long numbers are skipped, never a 500., test_compare_dedupes_and_caps(), test_compare_matches_summary() (+3 more)

### Community 22 - "test_summary.py"
Cohesion: 0.16
Nodes (13): _children_totals(), _first(), Tests for GET /clade/{taxid}/summary.  DB-backed tests use the shared ``client``, A species with data on a subspecies counts that data: its totals equal the     r, An informal species is one unit that is not a species: the clades above it     c, A clade's totals count every record under it, whatever rank it sits on., Guard: CladeMetadata field order == the SELECT column order in     queries.py, s, A below-species taxon reports is_infraspecific, n_rows==1, and its subtree     t (+5 more)

### Community 23 - "main"
Cohesion: 0.17
Nodes (14): _apply_schema(), main(), Connection, DataFrame, Build: NCBI taxdump -> ``taxon``; fresh NCBI/Annotrieve/ENA fetches -> per-recor, Stream (taxid, name, rank, parent_id, path) tuples for COPY — a     generator so, Apply every ``*.sql`` in ``schema_dir`` (idempotent DDL) so the build can     ru, Build the (taxid, rank, path) frame the rollup joins against. (+6 more)

### Community 24 - "load.py"
Cohesion: 0.21
Nodes (15): _copy_frame(), load_annotation(), load_assembly(), load_clade_features(), load_dataset_meta(), load_taxon(), Connection, DataFrame (+7 more)

### Community 25 - "Landing.tsx"
Cohesion: 0.17
Nodes (13): getGaps(), getOverview(), FeaturedClade, GapItem, SearchIcon(), RandomCladeButton(), Clade, FEATURED_CLADES (+5 more)

### Community 26 - "test_breakdown.py"
Cohesion: 0.16
Nodes (5): _is_descending(), Tests for GET /clade/{taxid}/breakdown against the live DB.  Uses Eukaryota (275, test_breakdown_default_sort_is_species_count(), test_breakdown_sort_by_total_assemblies(), _totals()

### Community 27 - "taxdump.py"
Cohesion: 0.22
Nodes (14): build_paths(), _iter_dmp(), iter_taxon_rows(), parse_names(), parse_nodes(), Path, Parse an NCBI taxdump into rows for the ``taxon`` table. No ETE3.  Input: an unp, Yield a ``TaxonRow`` for every node in the taxdump directory. (+6 more)

### Community 28 - "GapsPage.tsx"
Cohesion: 0.22
Nodes (12): CompareIcon(), DashboardIcon(), IconProps, MapIcon(), TreeIcon(), CladeView, VIEWS, FINER (+4 more)

### Community 29 - "test_children.py"
Cohesion: 0.14
Nodes (13): Tests for GET /taxon/{taxid}/children — the tree lazy-expand endpoint.  Exercise, Eukaryota's direct children come back sorted by species count desc, each     car, total is the pre-paging count; limit/offset return disjoint slices., A different sort keeps the same child set but reorders it by that metric., A childless taxon returns an empty list (not a 404), and its parent's     has_ch, A species' children are below-species (is_infraspecific True); a genus'     chil, An unknown taxid is a 404, distinct from 'present but childless'., test_children_infraspecific_flag() (+5 more)

### Community 30 - "test_taxdump.py"
Cohesion: 0.23
Nodes (13): ancestors(), descendants(), Return ``root`` plus every taxid whose lineage passes through it.      Inverts `, Return the strict ancestors of ``taxid`` (root-inclusive, excludes     ``taxid``, Path, Unit tests for the taxdump parser + ltree path builder.  Uses a tiny hand-writte, test_ancestors(), test_descendants() (+5 more)

### Community 31 - "Dashboard.tsx"
Cohesion: 0.27
Nodes (8): getAbout(), getChildren(), MetricConfig, ResourceSummary, MetricCard(), SpeciesLinks(), SubspeciesSection(), externalUrl()

### Community 32 - "ComparePage.tsx"
Cohesion: 0.19
Nodes (12): extractDetail(), getBreakdown(), getBreakdownQuality(), getCompare(), getQualityConfig(), unwrap(), CompareGroup, ComparePage() (+4 more)

### Community 33 - "compilerOptions"
Cohesion: 0.17
Nodes (11): compilerOptions, allowSyntheticDefaultImports, composite, module, moduleResolution, outDir, skipLibCheck, strict (+3 more)

### Community 34 - "logging_config.py"
Cohesion: 0.20
Nodes (9): configure_logging(), JsonFormatter, Structured JSON logging for the API.  One JSON object per line to stdout, so a c, Render a log record as a single-line JSON object., Point the root logger at a single JSON stdout handler at ``LOG_LEVEL``.      Ide, lifespan(), FastAPI, Configure structured logging, then open the DB pool (see db.lifespan). (+1 more)

### Community 36 - "Deployment and operations"
Cohesion: 0.18
Nodes (11): Behind a reverse proxy (TLS), Configuration, Data updates, Deployment and operations, Health checks and troubleshooting, Install, Requirements, Running from a fork (+3 more)

### Community 37 - "db.py"
Cohesion: 0.27
Nodes (9): lifespan(), pool_max_size(), FastAPI, Postgres connection pool + FastAPI wiring for the read-only serving path.  Servi, Most DB connections the API holds at once (``DB_POOL_MAX``, default 4).      Kep, Per-statement time limit for API queries (``DB_STATEMENT_TIMEOUT_MS``,     defau, Open the connection pool for the app's lifetime, close it on shutdown., statement_timeout_ms() (+1 more)

### Community 38 - "metrics.py"
Cohesion: 0.20
Nodes (4): Test for GET /metrics-config — the static card chrome the frontend renders., Test for GET /quality-config — the quality-dimension card chrome (the analogue o, EukaHub shared domain model.  Re-exports the metric config (the single source of, Single source of truth for the four resource metrics tracked per clade.  Ported

### Community 39 - "test_records.py"
Cohesion: 0.20
Nodes (9): Tests for the per-record drill-down endpoints: ``GET /taxon/{taxid}/assemblies``, Homo sapiens assemblies: live assembly-quality stats + real records., total is the pre-paging subtree count; limit/offset return disjoint slices., Homo sapiens annotations: BUSCO/gene stats, records default-sorted by     BUSCO, An unknown taxid is a 404 on both per-record endpoints., test_annotations_human_busco_sorted(), test_assemblies_human(), test_assemblies_pagination_stable_total() (+1 more)

### Community 40 - "test_restore_snapshot.py"
Cohesion: 0.20
Nodes (3): Unit tests for the snapshot restore helpers.  The promote/rollback paths rename, A dump carries no planner statistics; the swap must not go live without them., test_staging_is_analyzed_before_it_is_verified()

### Community 41 - "EukaHub"
Cohesion: 0.20
Nodes (10): Acknowledgements, Data refresh, Data sources, Documentation, EukaHub, Features, License, Repository layout (+2 more)

### Community 42 - "test_breakdown_quality.py"
Cohesion: 0.22
Nodes (3): Tests for GET /clade/{taxid}/breakdown/quality against the live DB.  The per-buc, Every quality bucket is a rank-`rank` taxon under the root (i.e. a tile)., test_breakdown_quality_buckets_are_breakdown_taxa()

### Community 43 - "test_overview.py"
Cohesion: 0.22
Nodes (7): Tests for GET /overview — the landing-page totals + featured groups.  Rebuild/sl, The global totals are Eukaryota's rollup — cross-check against the summary     e, Featured groups are a subset of the configured set, in configured order,     eac, Mammalia (40674) is present in both prod and the CI slice, so it must     surfac, test_overview_featured_shape(), test_overview_features_mammalia(), test_overview_totals_match_eukaryota_summary()

### Community 44 - "Data model"
Cohesion: 0.22
Nodes (9): Build and checks, Data model, How queries use it, Scope, Sizes (full dataset, September 2026), Sources, Species and placeholder taxa, Tables (+1 more)

### Community 45 - "test_export.py"
Cohesion: 0.36
Nodes (5): _parse(), Tests for GET /clade/{taxid}/export.tsv — the full-breakdown TSV download., test_export_exclude_empty_matches_filtered_total(), test_export_full_matches_breakdown_total(), test_export_headers_and_schema()

### Community 46 - "CLAUDE.md"
Cohesion: 0.25
Nodes (6): Commands, Conventions, Invariants, Map, Performance rules, Project

### Community 47 - "schema.ts"
Cohesion: 0.29
Nodes (6): api, components, $defs, operations, paths, webhooks

### Community 48 - "cached_frame"
Cohesion: 0.29
Nodes (6): Any, cached_frame(), DataFrame, Path, Resumable source snapshots.  Fetching all of Eukaryota is slow (datasets ~68k as, Return ``name``'s rows as a DataFrame.      Reuses ``<snapshot_dir>/<name>.parqu

### Community 49 - "database_url"
Cohesion: 0.29
Nodes (7): database_url(), Taxa below an informal species are single units too., test_children_of_informal_species_are_infraspecific(), Eukaryota's summary: stable taxonomy facts + structural invariants that     surv, A taxon present in `taxon` but absent from the rollup returns zeros., test_summary_eukaryota(), test_summary_zero_filled()

### Community 50 - "Contributing to EukaHub"
Cohesion: 0.29
Nodes (7): Branches and commits, Changing the API, Checks to run before a pull request, Code conventions, Contributing to EukaHub, Development setup, License

### Community 51 - "Design decisions"
Cohesion: 0.29
Nodes (6): Build, Data and storage, Delivery to servers, Design decisions, Interface, Serving

### Community 52 - "metrics_config"
Cohesion: 0.27
Nodes (4): metrics_config(), The tracked metrics — static card chrome the frontend renders once,     keyed by, Return the per-taxon external link rendered in the card., MetricConfig

### Community 54 - "Architecture"
Cohesion: 0.33
Nodes (6): Architecture, Components, Data updates, Repository layout, Request path, Resource budget

### Community 55 - "fetch_reads.py"
Cohesion: 0.40
Nodes (5): fetch_reads(), _query_ena(), Fetch per-taxon RNA-Seq run counts from EBI ENA.  Ports Euka-Survey's ``get_read, POST the ENA portal query and return the full JSON payload (list of     ``{tax_i, Return per-taxon RNA-Seq run counts as rows of ``{taxid, short, long}``.      ``

### Community 56 - "conftest.py"
Cohesion: 0.50
Nodes (4): client(), _db_available(), Shared fixtures for the API tests.  The endpoint tests exercise the full stack a, A TestClient with the connection pool open (via lifespan). Skips the     request

### Community 59 - "lowmem-test.sh"
Cohesion: 0.50
Nodes (3): hit(), POSTGRES_PASSWORD, lowmem-test.sh script

### Community 60 - "get_conn"
Cohesion: 0.50
Nodes (4): get_conn(), Connection, Request, Per-request connection, returned to the pool when the request ends.

### Community 61 - "overview"
Cohesion: 0.50
Nodes (4): overview(), Landing-page "at a glance": global totals across the eukaryotic tree plus     a, OverviewTotals, Global "at a glance" totals across the eukaryotic tree (Eukaryota's     rollup)

### Community 62 - "quality_config"
Cohesion: 0.50
Nodes (3): quality_config(), The annotation/assembly-quality stats — static card chrome rendered once,     ke, QualityStatConfig

### Community 65 - "eukahub"
Cohesion: 0.83
Nodes (4): eukahub, eukahub-api, eukahub-core, eukahub-pipeline

## Knowledge Gaps
- **146 isolated node(s):** `POSTGRES_PASSWORD`, `name`, `private`, `version`, `type` (+141 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `TargetRank` connect `queries.ts` to `BreakdownMap.tsx`, `GapsPage.tsx`, `clade_breakdown`?**
  _High betweenness centrality (0.093) - this node is a cross-community bridge._
- **Why does `main()` connect `main` to `rollup.py`, `test_fetch.py`, `restore_snapshot.py`, `placeholders.py`, `cached_frame`, `fetch_reads.py`, `load.py`, `taxdump.py`, `test_taxdump.py`?**
  _High betweenness centrality (0.059) - this node is a cross-community bridge._
- **Why does `gaps()` connect `clade_breakdown` to `main.py`, `queries.py`, `Metric`, `queries.ts`?**
  _High betweenness centrality (0.052) - this node is a cross-community bridge._
- **Are the 28 inferred relationships involving `CladeMetadata` (e.g. with `FilterLogic` and `TaxonNotFound`) actually correct?**
  _`CladeMetadata` has 28 INFERRED edges - model-reasoned connections that need verification._
- **Are the 25 inferred relationships involving `Metric` (e.g. with `AnnotationList` and `AnnotationRecord`) actually correct?**
  _`Metric` has 25 INFERRED edges - model-reasoned connections that need verification._
- **Are the 25 inferred relationships involving `QualityStat` (e.g. with `AnnotationList` and `AnnotationRecord`) actually correct?**
  _`QualityStat` has 25 INFERRED edges - model-reasoned connections that need verification._
- **Are the 22 inferred relationships involving `main()` (e.g. with `download_taxdump()` and `fetch_annotations()`) actually correct?**
  _`main()` has 22 INFERRED edges - model-reasoned connections that need verification._