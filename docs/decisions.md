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
- **Counts are rolled up at build time; medians are computed on request.** Counts
  add up a tree, so every clade's totals are precomputed once. Medians and "best of"
  statistics do not add up, so they are computed from the per-record tables, which
  are small enough (tens of thousands of rows) for that.
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
  one expensive request from taking the server down.
- **Wikipedia summaries go through the API**, not the browser: Wikipedia asks for a
  descriptive User-Agent, which browsers cannot set, and the API can cache each
  summary. A failure just hides the card.

## Interface

- **The Tree of Life is a radial tree in SVG**, using `d3-hierarchy` and `d3-shape`
  for layout only. The radial form is the recognizable "tree of life"; SVG keeps it
  accessible and themeable; lazy expansion keeps the node count manageable.
- **The breakdown is a click-to-drill treemap (the "data map").** Tile area is the
  number of species (or assemblies) and colour one chosen measure, so a large, pale
  tile is a large group with little data. Clicking drills to the next taxonomic
  rank, so no rank selector is needed.
- **Colour follows one scheme:** one sequential ramp per measure, light to dark in
  both themes, and text alternatives (lists, tables, outlines) for every chart.
