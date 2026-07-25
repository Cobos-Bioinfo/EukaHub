# Data model & database choice

This is the core design document. It answers three questions you asked:

1. Columnar vs relational?
2. SQL vs NoSQL (graph DBs)?
3. How to store the taxonomy: `id + parent_id`, `id + full lineage`, or
   something else?

The short version up top, then the reasoning.

## TL;DR

- **Serving engine: PostgreSQL** (relational, row-oriented). The workload is
  point lookups and small bounded subtree reads, not big analytical scans.
  MongoDB would also have fit (read-only makes denormalization safe), but
  Postgres won the fork for `ltree`, recursive CTEs, and breadth — see
  [`../DECISIONS.md`](../DECISIONS.md).
- **Not a graph database.** The taxonomy is a *strict tree* (every node has
  exactly one parent). That is the trivial case that relational and document
  stores already handle well. A graph DB (Neo4j) is built for many-to-many,
  variable-relationship traversal and would add a heavy server and a niche
  skill for no payoff here.
- **Columnar has one legitimate home: the offline build**, not serving. The
  weekly rollup (summing features up ~1.8M lineages) is an analytical job that
  a columnar engine (DuckDB / Polars) does beautifully. Serving stays
  row-oriented.
- **Store the tree as adjacency (`parent_id`) AND a materialized lineage**
  (an ancestors path/array). Not one or the other. `parent_id` gives you the
  canonical structure, cheap children lookups (for lazy-expand in the future
  Tree of Life view), and easy rebuilds. The materialized lineage makes "all
  descendants of X at rank R" a single indexed query with no recursion, which
  is exactly the breakdown question and the thing that killed the old design.

## Why this is not the textbook "big data" problem

The single most important fact: **this app is read-only at runtime.** The
dataset is rebuilt on a schedule offline and served unchanged. No user writes,
no transactions, no concurrency on writes, no schema migrations under load.

That deletes most of the reasons people reach for heavy infrastructure, and it
*unlocks* two things that would be dangerous in a read-write system but are
free here:

- **Denormalization is safe.** We can duplicate data (store each node's full
  lineage, embed feature counts onto taxon rows) because there is no update
  anomaly risk when the whole dataset is rebuilt atomically each cycle.
- **Expensive-to-mutate layouts are fine.** Tree encodings whose only real
  downside is costly inserts/moves (nested sets, materialized paths) cost us
  nothing, because we never mutate in place. We compute the layout once per
  build.

Keep this lens on every choice below.

## Question 1 — Columnar vs relational

These are not opposite ends of one axis, and conflating them is the most common
beginner trap, so let me separate the two things hiding inside the question:

- **Data model axis:** *relational* (tables with keys and joins) vs
  *non-relational* (documents, key-value, graph). This is Question 2.
- **Storage-layout axis:** *row-oriented* (OLTP; Postgres, SQLite, MongoDB
  store a record's fields together) vs *column-oriented* (OLAP; DuckDB,
  ClickHouse, Parquet store each column together). This is what "columnar"
  actually means. Note that DuckDB is *columnar AND relational/SQL* — the two
  axes are independent.

The layout choice follows the access pattern:

| Access pattern | Wants |
|---|---|
| "Fetch this taxon's row / a few hundred taxa's rows by key" | **Row store** |
| "Scan/aggregate millions of rows across a few columns" | **Column store** |

Our serving access pattern is the first row: get one taxon's rollup (summary),
or get the few-thousand taxa at rank R under a root (breakdown). Both fetch
whole records by key or by an indexed predicate. That is a **row store**.

Where columnar earns its place is the **offline pipeline**. Rolling raw
per-species counts up through ~1.8M lineages into per-clade aggregates is a
classic analytical scan-and-group-by. Doing that in **DuckDB or Polars** is
faster and cleaner than the current Python dict-accumulation loop, and it is a
genuinely resume-worthy modern-data-stack skill to demonstrate. So:

> **Row-oriented relational DB for serving; columnar (DuckDB/Polars) is a
> good, optional tool inside the build step.**

## Question 2 — SQL vs NoSQL (and graph DBs)

The data has two shapes: a **hierarchy** (the taxonomy) and **tabular metrics**
(per-clade counts) that we read together. Evaluate each store against that:

- **Graph DB (Neo4j, etc.).** Tempting because "tree of life." But a taxonomy
  is a *single-parent tree* — the simplest possible graph. Graph databases pay
  off when relationships are many-to-many, typed, and traversed at variable
  depth with unpredictable shapes (social graphs, fraud rings, recommendations).
  A strict hierarchy does not need that machinery, and relational/document
  stores model trees well with the patterns below. Against it: a heavy server
  to host, a query language (Cypher) that is a narrower skill, and awkward joins
  back to the tabular metrics. **Not recommended.** (Interesting to prototype;
  not the foundation.)
- **Document store (MongoDB).** Normally I would push back on a document store
  for join-shaped data. But two things flip it here: (a) read-only +
  denormalization-safe means we can embed the feature counts directly on each
  taxon document and store an `ancestors` array, so the breakdown is a single
  indexed `find({ancestors: X, rank: R})` with no `$lookup`; (b) **it is what
  guigolab/Annotrieve run**, so it is the strongest *host-alignment* choice.
  Technically fine here. See the tree patterns below — Mongo's own docs
  literally document "array of ancestors" and "materialized path" as tree
  models.
- **Relational SQL (PostgreSQL / SQLite).** The most natural fit: taxonomy in
  one or two tables, metrics in another, joined on `taxid`. Postgres adds two
  things that are *purpose-built* for this app: recursive CTEs, and the
  **`ltree`** extension — a labelled-tree type with GiST indexes and
  ancestor/descendant operators (`@>`, `<@`) that is the textbook tool for
  taxonomies. It is also the broadest, most transferable skill. **This is the
  chosen engine** (see [`../DECISIONS.md`](../DECISIONS.md)); MongoDB was the
  runner-up on host-alignment grounds.

Net: **PostgreSQL (SQL relational) chosen; MongoDB was the respectable
host-aligned alternative; graph DB is not worth it.** The *tree-storage design
below is nearly identical* whichever of the two we had picked, so nothing in the
modeling changes.

## Question 3 — How to store the taxonomy tree

This is the heart of it. Four classic patterns, judged against our two queries
(**descendants**: "everything under X at rank R" = the breakdown;
**ancestors**: "the lineage of X" = the breadcrumb) and remembering that
**writes are free-ish because we rebuild offline**.

### A. Adjacency list — `id + parent_id`
Each node stores only its direct parent.
- Ancestors: walk up parent by parent (cheap; depth is ~20-35 max).
- Descendants: **requires recursion** (recursive CTE / `$graphLookup`).
  Descending Eukaryota to species touches ~1.6M nodes every time.
- Children of X: trivial, one indexed lookup on `parent_id`. **This is the
  best pattern for lazy-expand in an interactive tree.**
- Storage: minimal. Normalized and canonical.

### B. Materialized path / ancestors — `id + full lineage`
Each node also stores its path from the root, e.g. `2759.33208.7711.40674` (a
string / `ltree`) or `[2759, 33208, 7711, 40674]` (an array).
- Descendants of X at rank R: **single indexed query, no recursion** —
  `path <@ 'X'` (ltree) / `ancestors: X` (array) plus `rank = R`.
- Ancestors: **free** — it is literally the stored path.
- Storage: denormalized; each node carries its whole lineage (~20-35 entries).
  Costs a few hundred MB for the eukaryote subtree, comparable to today's DB —
  but *general* (works for any root, not six) and it removes ETE3.
- The mutation downside (moving a node rewrites its subtree's paths) **does not
  apply to us** — we rebuild.

### C. Closure table — one row per (ancestor, descendant) pair
Descendant/ancestor queries become simple joins, no recursion, very flexible.
- But for 1.8M nodes at depth ~25 this is **~30-45M rows** — bigger than the
  old bloated DB. The generality is not worth that storage here. **Skip.**

### D. Nested set — `lft`/`rgt` interval numbering
A DFS numbering where descendants are `WHERE lft BETWEEN X.lft AND X.rgt`.
- Descendants: single range scan, no recursion, **two integers per node** (tiny).
- Ancestors: `WHERE lft < X.lft AND rgt > X.rgt`.
- Its notorious weakness (any insert renumbers the tree) **is irrelevant to us**
  because we rebuild. Genuinely viable. But it is less self-documenting than a
  path, harder to reason about, and interval-overlap predicates are less
  ergonomic than `ltree`'s operators. A close second to B.

### Verdict: store **A + B together**
Keep `parent_id` (adjacency) for the canonical structure, cheap children
lookups (future lazy-expand tree), and simple rebuilds. Add a **materialized
lineage** (Postgres `ltree` path, or a Mongo `ancestors` array) for O(1)
breadcrumbs and single-query rank breakdowns. This is cheap, and it is the
direct fix for the old `precomputed_taxa` bloat: the breakdown that used to
require a 3.5M-row hard-coded cache (six roots only) becomes one indexed
predicate that works for *any* taxon.

So the answer to your bullet is: **not "`id+parent` OR `id+lineage`" — store
both.** `parent_id` for structure, lineage for fast subtree/lineage queries.

## Proposed schema (relational sketch)

Engine-agnostic; shown as Postgres. The Mongo shape is the same idea embedded
into one `taxa` collection.

```sql
-- The taxonomy, loaded from NCBI taxdump (nodes.dmp + names.dmp). No ETE3.
CREATE TABLE taxon (
    taxid       INTEGER PRIMARY KEY,
    name        TEXT      NOT NULL,      -- scientific name
    rank        TEXT      NOT NULL,      -- 'species','genus',... (indexed)
    parent_id   INTEGER   REFERENCES taxon(taxid),   -- adjacency (A)
    path        LTREE     NOT NULL       -- materialized lineage (B)
);
CREATE INDEX ON taxon (parent_id);
CREATE INDEX ON taxon (rank);
CREATE INDEX ON taxon USING GIST (path);          -- descendant/ancestor ops

-- Precomputed rollups: one row per taxon at ANY rank (kept from Euka-Survey;
-- ~34 MB, computed offline). c_* = species covered, s_* = summed counts.
CREATE TABLE clade_features (
    taxid   INTEGER PRIMARY KEY REFERENCES taxon(taxid),
    n_rows  INTEGER,                     -- species in subtree
    c_ass INTEGER, c_ann INTEGER, c_rna INTEGER, c_lng INTEGER,
    s_ass INTEGER, s_ann INTEGER, s_rna INTEGER, s_lng INTEGER
);
```

The two runtime queries become:

```sql
-- Q1 Summary: one indexed lookup.
SELECT * FROM clade_features WHERE taxid = :root;

-- Q2 Breakdown: descendants of :root at :rank, joined to their rollups.
-- Single indexed subtree scan via ltree; no recursion, no precomputed_taxa,
-- works for ANY root. Filter/sort/limit push down as today.
SELECT t.taxid, t.name, f.*
FROM taxon t
JOIN clade_features f USING (taxid)
WHERE t.path <@ (SELECT path FROM taxon WHERE taxid = :root)
  AND t.rank = :rank
ORDER BY f.s_ass DESC
LIMIT :n;
```

(We may still *materialize* the breakdown for the handful of huge common roots
as a cache, but as an optimization over a correct general query, not as the
only way the feature works.)

## What we keep from Euka-Survey

- The **offline rollup** (`precomputed_clade_features` becomes `clade_features`)
  — its logic is sound; only the storage target changes.
- The **metric config** (`src/metrics.py`) as the single source of truth for the
  four resources. It should generate both the DB column set and the frontend's
  TypeScript types so they cannot drift.
- The **filter/sort/limit** semantics (and the SQL/Python parity discipline).

## What we delete

- `precomputed_taxa` and its covering index (86% of the old DB, six roots only).
- **ETE3** at build time (load taxdump directly) and at runtime (taxonomy lives
  in our DB now).
- The whole PyQt5 / matplotlib / subprocess tree-rendering path.
