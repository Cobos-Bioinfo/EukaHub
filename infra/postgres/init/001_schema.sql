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
-- Stage B (data-model enrichment, docs/data-model.md) extends clade_features
-- with additive quality columns (n_ass_complete/_chromosome/_scaffold/_contig,
-- n_reference, s_bases) *together with* the rollup that fills them and
-- eukahub_core.metrics.clade_feature_columns(), so the single-source invariant
-- (this table mirrors that function) stays intact.

-- Per-record tables (data-model.md: Enriched data model). Small, read-only, and
-- independently sourced, so drill-down lists + on-demand distribution stats
-- (median N50 / genome size / gene count, BUSCO) are cheap ltree subtree scans
-- rather than a heavy per-clade rollup (medians are not additive).

-- One row per genome assembly. Source: NCBI datasets CLI (ALL assemblies).
--   taxid is externally sourced (may sit on a strain below species) and carries
--   NO FK: the pipeline filters to taxids present in `taxon`, but keeping the
--   load robust to merged/deleted NCBI taxids matters more than a DB-level FK.
CREATE TABLE IF NOT EXISTS assembly (
    assembly_accession    TEXT PRIMARY KEY,        -- GCA_.../GCF_...
    taxid                 INTEGER NOT NULL,
    assembly_level        TEXT,     -- Complete Genome | Chromosome | Scaffold | Contig
    contig_n50            BIGINT,
    scaffold_n50          BIGINT,
    total_sequence_length BIGINT,   -- genome size
    gc_percent            REAL,
    refseq_category       TEXT,     -- 'reference genome' | 'representative' | NULL
    release_date          DATE,
    submitter             TEXT,
    source_database       TEXT,     -- GenBank | RefSeq
    bioprojects           TEXT[],   -- deep-link
    download_url          TEXT      -- deep-link to the actual FASTA
);
CREATE INDEX IF NOT EXISTS assembly_taxid_idx ON assembly (taxid);

-- One row per functional annotation. Source: Annotrieve /annotations (annotated
-- subset, ~17k). `assembly_accession` is a plain indexed column, NOT an FK:
-- assemblies (datasets) and annotations (Annotrieve) are fetched independently,
-- so an annotation may reference an assembly absent from `assembly`.
CREATE TABLE IF NOT EXISTS annotation (
    annotation_id        TEXT PRIMARY KEY,          -- Annotrieve md5 checksum
    assembly_accession   TEXT,
    taxid                INTEGER NOT NULL,
    source_database      TEXT,      -- Ensembl | NCBI | ...
    provider             TEXT,      -- community | ...
    release_date         DATE,
    gff_url              TEXT,      -- deep-link to the GFF
    gene_count           INTEGER,   -- features_summary.root_type_counts.gene
    protein_coding_count INTEGER,   -- features_statistics coding total
    busco_complete       REAL,      -- busco.complete (%)
    busco_single_copy    REAL,
    busco_duplicated     REAL,
    busco_lineage        TEXT       -- e.g. eukaryota_odb12
);
CREATE INDEX IF NOT EXISTS annotation_taxid_idx    ON annotation (taxid);
CREATE INDEX IF NOT EXISTS annotation_assembly_idx ON annotation (assembly_accession);
