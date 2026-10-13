# Design decisions

Why EukaHub is built the way it is. Each entry: the decision, then the reason.
EukaHub rewrites [Euka-Survey](https://github.com/Cobos-Bioinfo/Euka-Survey), a
Streamlit app that answered the same questions but was slow to build and to serve.

## Data and storage

- **Serving is read-only; the dataset is rebuilt offline.** Nothing writes at request
  time, so the data can be precomputed and denormalized freely, and an update is a
  swap of complete datasets rather than an in-place migration.
- **PostgreSQL, relational.** The data is a single-parent tree plus per-taxon
  numbers. Postgres has `ltree` (lineage type with ancestor/descendant operators and
  an index for them) and mature tooling. A document store would also have worked; a
  graph database buys nothing for a strict tree.
- **The tree is stored twice: `parent_id` and a materialized `ltree` path.**
  `parent_id` makes "children of X" a single lookup (the Tree of Life expands
  lazily); the path makes "all descendants of X at rank R" a single indexed query
  for any root. This replaces Euka-Survey's per-root precomputed tables and its
  ETE3 dependency.
- **Counts and each clade's quality statistics are computed at build time.** Counts
  add up a tree, so every clade's totals are summed once. Medians and "best of"
  statistics do not add up, so the build computes each clade's from its own
  records, fanned out to every ancestor as the counts are (`clade_stats`, about
  52,600 rows). They were computed per request until October 2026, which read every
  record under each clade: about half a second for a page of clades, growing with
  the records (tens of seconds at 30 times today's assemblies). A lookup costs the
  same at any scale. Only a set of clades (include minus exclude) still needs its
  records, since medians cannot be subtracted.
- **Assemblies and annotations are stored per record; RNA-Seq only as counts.**
  Per-record data gives download links and quality statistics where it is cheap;
  RNA-Seq has millions of runs and adds little per record.
- **Source split:** assemblies and their quality fields from NCBI Datasets (all
  assemblies); annotation quality (BUSCO, gene counts, GFF links) from Annotrieve,
  which already computes it; RNA-Seq run counts from ENA.
- **A species is a taxon with a formal species name.** More than half of NCBI's
  eukaryote species-rank taxa are placeholders ("Homo sp.", "uncultured eukaryote",
  "cf." identifications, crosses between species); counted as species they would
  more than halve every coverage figure. The rule is Lifemap's name filters plus a
  binomial check, so it follows from the taxonomy alone with no curated list. Those
  without data are dropped at build time, which also halves the `taxon` table; those
  with data are kept as `informal species`, so no record is lost.
- **Every record counts toward every clade above it, whatever rank it is attached
  to.** A species whose genomes are all filed under its subspecies or varieties
  (banana has 10) is covered, and every total equals the clade's record list. Finer
  taxa and informal species are not counted as extra species, which would inflate
  the species count (agreed with the Annotrieve maintainer in issue #31).
- **Every annotation Annotrieve serves counts**, including community-contributed ones
  such as TOGA2 projections, not only those from GenBank, RefSeq and Ensembl. Any
  usable GFF is better than none for someone looking for an annotated genome, and
  excluding them would hide about 2,000 annotated assemblies. The record list shows
  each annotation's source, so they can be told apart.

## Build

- **Polars for the rollup** (over DuckDB; pandas ruled out). The lineage fan-out
  (every species counted in each of its ancestors) is a split, explode and group-by
  over tens of millions of rows, which Polars runs in seconds in-process.
- **The pipeline runs on GitHub Actions, not on the server.** The server only
  restores finished datasets, so it needs no build tooling, source credentials or
  CPU headroom.
- **Sources are streamed, never held whole in memory.** Each fetcher parses its
  source as it arrives and the rows go to disk in batches, so the build's memory does
  not grow with the sources. ENA's runs (about 8 million) come as two TSV queries,
  short-read and long-read, counted per taxon line by line; ENA can end a large
  response early in any format, so each query is checked against ENA's own count. A
  source's snapshot appears only once its fetch completes, so a failed fetch never
  leaves a partial one to be reused.
- **A dataset is published only after invariant checks pass**, and the same checks
  run again on the server before it goes live.

## Delivery to servers

- **Servers pull a public GitHub Release.** Chosen over a private-repo token, an SSH
  push from CI, or building on the server: nothing to store, rotate or expire, and
  no inbound access to approve. Releases rather than workflow artifacts, because
  artifacts are deleted after 90 days.
- **Swap whole databases by renaming them.** The new dataset is restored into
  `<db>_next` while the live one keeps serving, verified, then swapped in by
  renaming; the previous one stays as `<db>_prev` for rollback. Databases rather
  than schemas, because the `ltree` and `pg_trgm` extensions live in `public`.
- **The first install is the same path as an update.** An empty database simply
  looks outdated, so bringing the stack up installs the data.
- **Failure is safe, not impossible.** Upstream APIs will change eventually, and the
  monthly rebuild will then fail. It fails closed: nothing is published, servers
  keep the previous data, and the scheduled run opens an issue.

## Serving

- **FastAPI** for the API: it shares Python with the pipeline and generates the
  OpenAPI description, from which the web app's TypeScript types are generated, so
  client and server cannot silently disagree.
- **React + TypeScript SPA built with Vite**, no server-side rendering: every page
  is a view over API data.
- **No user accounts.** The API serves public, read-only data derived from public
  sources. Abuse is handled with rate limiting at the reverse proxy, not logins.
- **Sized for one CPU core and about 1 GB of RAM.** A 15 s per-query limit, a
  four-connection pool, no parallel query workers, and an nginx response cache keep
  one expensive request from taking the server down. The TSV report streams in
  batches, so the API's memory stays flat whatever its size, and it has no size
  limit: it grows only with the taxonomy (about 45 MB for every taxon today). It is
  not cached (`no-store`), which keeps nginx's cache for the small JSON responses
  the interface repeats.
- **Deployment settings are configuration, not code.** Links, the privacy contact,
  the Wikipedia summary endpoint and the curated groups are read by the API at
  startup (from `infra/.env` and an optional `infra/config/groups.json`), and the web
  app gets them from `/api/config`, so changing one needs a restart, not a new image.
  Only the API container reads the groups file, which also feeds the landing-page
  numbers. Every setting has a default, and an invalid one is logged and replaced by
  its default, because a typo should not take an unattended site down. The pipeline's
  source addresses are GitHub Actions repository variables instead, since the
  pipeline runs there; there an invalid value stops the build, because a build
  against a source nobody chose must not publish.
- **Custom groups are sets of clades, computed per request.** A set is whole clades
  included, minus clades inside them excluded, so its counts are sums and differences
  of `clade_features` rows. Its quality stats are medians and maxima, which cannot be
  subtracted, so they come from the records in the set. The API keeps the two
  concerns apart: `/config` lists the deployment's groups and their clades, and
  `/taxons/aggregates` computes any set. Nothing is precomputed, so a deployment
  changes its groups with a restart, not a rebuild. Groups under one parent may not
  overlap, so that they and the parent's "rest" group always add up to the parent.
- **The API has one main resource, taxons, named like Annotrieve's.** A taxon is
  one object everywhere: `/taxons/{taxid}` returns it, `/taxons` lists it, and
  `/taxons/{taxid}/ancestors` gives the lineage as the same objects, root first.
  `/taxons` lists taxa by name, parent, rank under a taxon or taxid, sorted by any
  count or by the species still missing a resource (`gap_<key>`). Search, the tree's
  children, the data map, the gaps list, compare and the landing numbers are that
  one list with different filters, so each page's request is cached on its own and
  nothing is computed twice. Quality stats are a resource of their own,
  `/taxons/{taxid}/stats` and `/taxons/stats` (paged with the same parameters and
  cursors as `/taxons`), so a list that does not show them never reads them and no
  parameter changes a response's shape. Records are their own
  collections (`/assemblies`, `/annotations`), filtered by `within`, and
  `/taxons/report` is the whole list as TSV. Names follow Annotrieve's API
  (`/taxons`, `/ancestors`, `sort_by`, `sort_order`, `results`, `/report`), which the
  same people maintain and use.
- **Lists page with a cursor, not an offset.** Each list sorts on keys that end in
  a unique one (the taxid or the record's accession), and a page's `next` and
  `previous` cursors hold the key values of its last and first rows. The next query
  filters on those values instead of skipping `offset` rows, which Postgres reads
  and throws away, so a deep page costs what the first does and an indexed sort
  can start where the cursor points. The cursor is opaque base64url JSON naming its
  sort order; one from another order is refused with a 422. Records missing the
  sort field come last in either direction. Lists still report `total`; each filter
  set is counted once per dataset build and kept in a small in-process cache (about
  2 MB at most), since the data only changes when a new build is installed.
- **The root taxids stay in code**, in one constant per side
  (`eukahub_core.taxonomy` and `web/src/lib/taxonomy.ts`). The dataset is built and
  validated for Eukaryota, so another root needs a rebuild and new checks anyway.
- **The browser fetches Wikipedia summaries itself**, from the endpoint `/api/config`
  names. Wikipedia allows cross-origin requests and asks browsers to identify the tool
  with an `Api-User-Agent` header. Proxying them through the API held a database
  connection while Wikipedia answered and put an external service in the request
  path; the browser already loaded the thumbnails from Wikimedia anyway. A failure
  just hides the card.

## Interface

- **The current group is the app's state.** Every view of a group lives under
  `/clade/:taxid`: its Summary, Data map (`/map`), Records (`/records`), Tree of Life
  (`/tree`) and Gaps (`/gaps`), shown as tabs, with its lineage in the top bar
  (the first two ranks, a "…" menu with the ones in between, and the last two).
  Following the lineage, searching, clicking a tile on the Data map or looking inside
  a group on Gaps changes the group and keeps the view, so the address always names
  what is on screen and the browser's back button walks it. A species or a finer
  taxon has no Data map or Gaps, and a group without records no Records tab. The old
  addresses (`/map/:taxid`, `/tree/:taxid`, `/gaps?root=`) redirect. On a phone the
  pinned top bar is one line (brand, search, menu), and Compare and the theme move
  into the menu. Compare is the only page about several groups.
- **The Tree of Life is a radial tree in SVG**, using `d3-hierarchy` and `d3-shape`
  for layout only. The radial form is the recognizable "tree of life"; SVG keeps it
  accessible and themeable; lazy expansion keeps the node count manageable.
- **The breakdown is a click-to-drill treemap (the "Data map"), with a list beside
  it.** Tile area is the number of species (or assemblies) and colour one share, so a
  large, pale tile is a large group with little data. Clicking a tile makes it the
  current group, broken down by the next taxonomic rank; a "Show" menu picks a finer
  rank. Groups under 1% of the total share one tile (when there are three or more),
  which opens the list, since their own tiles would be too small to read or hit.
  The List view is the same breakdown as a table and holds the TSV download. Only
  shares colour the map (of species with each resource, of assemblies at chromosome
  level); genome size, gene counts and BUSCO stay in the tooltip and on the Summary.
  The view, measure, size and rank stay in the address (`?view=`, `?colour=`,
  `?size=`, `?rank=`).
- **Shares are coloured by six fixed ranges:** none (hatched grey, never the lightest
  step), under 1%, 1 to 5%, 5 to 20%, 20 to 50% and 50% or more, on one blue ramp for
  every measure, light to dark in both themes (the dark theme lifts its dark end so
  it clears the surface). Most shares are small: of the orders by assemblies, 35% have
  none, 6% under 1%, 19% 1 to 5%, 26% 5 to 20%, 8% 20 to 50% and 6% 50% or more, so a
  continuous 0 to 100% ramp left most of the map pale. The Data map uses them; the
  Tree of Life keeps a continuous ramp per measure until its own redesign. Any other
  magnitude gets one sequential ramp, and every chart has a text alternative (a list,
  a table or an outline).
