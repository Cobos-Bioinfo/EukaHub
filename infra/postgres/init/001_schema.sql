-- EukaHub schema — mirrors docs/data-model.md. Applied on first DB init.
-- Read-only at serve time; the whole dataset is rebuilt offline and swapped in.

CREATE EXTENSION IF NOT EXISTS ltree;
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- fast case-insensitive name search

-- The taxonomy, loaded from NCBI taxdump (nodes.dmp + names.dmp). No ETE3.
--   parent_id — adjacency (A): cheap children lookups + future lazy-expand.
--                The root (taxid 1) is its own parent. No FK during bulk load.
--   path      — materialized lineage (B): O(1) breadcrumbs + single-query
--                rank breakdowns via the ltree @>/<@ operators.
CREATE TABLE IF NOT EXISTS taxon (
    taxid       INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,        -- scientific name
    rank        TEXT    NOT NULL,        -- 'species','genus',...
    parent_id   INTEGER NOT NULL,
    path        LTREE   NOT NULL         -- root -> node, dot-separated taxids
);

CREATE INDEX IF NOT EXISTS taxon_parent_id_idx ON taxon (parent_id);
CREATE INDEX IF NOT EXISTS taxon_rank_idx      ON taxon (rank);
-- Descendant/ancestor operators for the breakdown + breadcrumb queries.
CREATE INDEX IF NOT EXISTS taxon_path_gist_idx ON taxon USING GIST (path);
-- Trigram index for the name-search endpoint (ILIKE '%q%' and prefix 'q%').
CREATE INDEX IF NOT EXISTS taxon_name_trgm_idx ON taxon USING GIN (name gin_trgm_ops);

-- Precomputed rollups: one row per taxon at ANY rank (computed offline).
-- Column set mirrors eukahub_core.metrics.METRICS (keys: ass, ann, rna, lng):
--   c_<key> = species covered (>=1 of that resource in the subtree)
--   s_<key> = total resource count summed across the subtree's species
-- Percentages (p_<key>) are derived in code, not stored.
CREATE TABLE IF NOT EXISTS clade_features (
    taxid   INTEGER PRIMARY KEY REFERENCES taxon(taxid),
    n_rows  INTEGER NOT NULL DEFAULT 0,  -- species in subtree
    c_ass   INTEGER NOT NULL DEFAULT 0,
    c_ann   INTEGER NOT NULL DEFAULT 0,
    c_rna   INTEGER NOT NULL DEFAULT 0,
    c_lng   INTEGER NOT NULL DEFAULT 0,
    s_ass   INTEGER NOT NULL DEFAULT 0,
    s_ann   INTEGER NOT NULL DEFAULT 0,
    s_rna   INTEGER NOT NULL DEFAULT 0,
    s_lng   INTEGER NOT NULL DEFAULT 0
);
