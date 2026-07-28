# Data model & database choice

The core design doc. Three questions, answered, then the schema.

## Answers up front

- **Serving engine: PostgreSQL** (relational, row-oriented). The workload is
  point lookups and small bounded subtree reads, not big analytical scans.
  MongoDB also fit (read-only makes denormalization safe); Postgres won for
  `ltree`, recursive CTEs, and breadth. See [`../DECISIONS.md`](../DECISIONS.md).
- **Not a graph database.** A taxonomy is a strict single-parent tree — the
  trivial case relational/document stores handle well. Neo4j's machinery
  (many-to-many, variable-depth traversal) buys nothing here.
- **Columnar (DuckDB/Polars) only in the offline build**, not serving. The
  weekly rollup (summing features up ~1.8M lineages) is an analytical
  scan-and-group-by that suits a columnar engine; serving stays row-oriented.
- **Store the tree as adjacency (`parent_id`) AND materialized lineage**
  together — not one or the other (see Question 3).

## Why this isn't a "big data" problem

**The app is read-only at runtime.** The dataset is rebuilt offline and served
unchanged — no user writes, transactions, or migrations under load. That unlocks
two things safely:

- **Denormalization is safe** — duplicate lineages, embed feature counts; no
  update-anomaly risk when the whole dataset is rebuilt atomically each cycle.
- **Expensive-to-mutate layouts are fine** — materialized paths / nested sets
  cost nothing, because we never mutate in place; we compute the layout once.

## Q1 — Columnar vs relational

Two independent axes: *data model* (relational vs document/graph — that's Q2) and
*storage layout* (row- vs column-oriented). Layout follows the access pattern:

| Access pattern | Wants |
|---|---|
| Fetch a taxon's row / a few hundred rows by key | **Row store** |
| Scan/aggregate millions of rows across few columns | **Column store** |

Serving = the first row (one taxon's rollup, or the taxa at rank R under a root).
So: **row-oriented relational DB for serving; columnar (DuckDB/Polars) inside the
offline build**, where the rollup is a classic scan-and-group-by (and a
resume-worthy modern-data-stack skill).

## Q2 — SQL vs NoSQL (and graph DBs)

The data is a **hierarchy** (taxonomy) + **tabular metrics** (per-clade counts)
read together. Against that:

- **Graph DB (Neo4j).** A single-parent tree is the simplest graph; graph DBs pay
  off for many-to-many, variable-depth traversal. Heavy server, niche skill
  (Cypher), awkward joins to the metrics. **Not recommended.**
- **Document store (MongoDB).** Read-only + denormalization make it viable: embed
  feature counts and an `ancestors` array, so the breakdown is one indexed
  `find({ancestors: X, rank: R})` with no `$lookup`. Also guigolab's stack, so the
  strongest host-alignment choice.
- **Relational SQL (PostgreSQL).** The natural fit: taxonomy + metrics joined on
  `taxid`. Adds recursive CTEs and **`ltree`** (labelled-tree type, GiST index,
  `@>`/`<@` ancestor/descendant operators) — purpose-built for taxonomies, and the
  broadest skill. **Chosen;** Mongo was runner-up on host-alignment.

The tree-storage design below is nearly identical whichever of the two we picked.

## Q3 — How to store the taxonomy tree

Judged against our two queries (**descendants** = breakdown, **ancestors** =
breadcrumb), remembering **writes are free** (we rebuild offline):

- **A. Adjacency (`id + parent_id`).** Ancestors: walk up (cheap; depth ~20-35).
  Descendants: needs recursion. Children of X: one indexed lookup — **best for
  lazy-expand** in an interactive tree. Minimal, canonical storage.
- **B. Materialized path/ancestors (`id + full lineage`).** Descendants at rank R:
  single indexed query, no recursion (`path <@ 'X'`). Ancestors: free (it's the
  stored path). Denormalized (~a few hundred MB), but general (any root) and it
  removes ETE3. The move-a-node mutation cost doesn't apply — we rebuild.
- **C. Closure table** (row per ancestor/descendant pair). Simple joins, but
  ~30-45M rows for our tree — bigger than the old bloated DB. **Skip.**
- **D. Nested set (`lft`/`rgt`).** Tiny (two ints/node) and viable, but less
  self-documenting than a path and interval predicates are less ergonomic than
  `ltree`. Close second to B.

**Verdict: store A + B together.** `parent_id` for canonical structure + cheap
children lookups (future lazy-expand); materialized lineage for O(1) breadcrumbs
and single-query rank breakdowns. This directly replaces `precomputed_taxa`: the
breakdown that needed a 3.5M-row six-root cache becomes one indexed predicate for
any taxon.

## Schema (Postgres sketch)

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

The two runtime queries:

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

(We may still materialize the breakdown for the handful of huge common roots as a
cache — an optimization over a correct general query, not the only path.)

## Reuse from Euka-Survey

- The **offline rollup** (`precomputed_clade_features` → `clade_features`).
- The **metric config** (`src/metrics.py`) as the single source of truth — it
  generates both the DB column set and the frontend TS types so they can't drift.
- The **filter/sort/limit** semantics (and the SQL/Python parity discipline).

## Delete

- `precomputed_taxa` + its covering index (86% of the old DB, six roots only).
- **ETE3** at build time (load taxdump directly) and at runtime.
- The whole PyQt5 / matplotlib / subprocess tree-rendering path.
