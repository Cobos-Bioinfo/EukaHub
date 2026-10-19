-- EukaHub serving schema, explained in docs/data-model.md. Applied when the database
-- is first created and again (idempotently) by the pipeline build.
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
    common_name TEXT,                    -- NCBI's GenBank common name ('human'), if any
    rank        TEXT    NOT NULL,        -- 'species','genus',...
    parent_id   INTEGER NOT NULL,
    path        LTREE   NOT NULL         -- root -> node, dot-separated taxids
);

CREATE INDEX IF NOT EXISTS taxon_parent_id_idx ON taxon (parent_id);
CREATE INDEX IF NOT EXISTS taxon_rank_idx      ON taxon (rank);
-- Descendant/ancestor operators for the breakdown + breadcrumb queries.
CREATE INDEX IF NOT EXISTS taxon_path_gist_idx ON taxon USING GIST (path);
-- Trigram indexes for the name search (ILIKE '%q%' and prefix 'q%'), which matches
-- scientific and common names.
CREATE INDEX IF NOT EXISTS taxon_name_trgm_idx ON taxon USING GIN (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS taxon_common_name_trgm_idx ON taxon USING GIN (common_name gin_trgm_ops);

-- NCBI taxids merged into another one (merged.dmp), so a link or a record that
-- still uses an old taxid finds the taxon it now belongs to.
CREATE TABLE IF NOT EXISTS taxon_merged (
    taxid       INTEGER PRIMARY KEY,     -- the old taxid
    merged_into INTEGER NOT NULL         -- its current taxid, in `taxon`
);

-- Precomputed rollups: one row per taxon at ANY rank (computed offline).
-- Column set mirrors eukahub_core.metrics.METRICS (keys: ass, ann, srt, lng):
--   c_<key> = species with >=1 of that resource on themselves or a finer taxon
--   s_<key> = total resource count in the subtree, at any rank
-- Percentages (p_<key>) are derived in code, not stored.
CREATE TABLE IF NOT EXISTS clade_features (
    taxid   INTEGER PRIMARY KEY REFERENCES taxon(taxid),
    n_rows  INTEGER NOT NULL DEFAULT 0,  -- species in subtree
    c_ass   INTEGER NOT NULL DEFAULT 0,
    c_ann   INTEGER NOT NULL DEFAULT 0,
    c_srt   INTEGER NOT NULL DEFAULT 0,
    c_lng   INTEGER NOT NULL DEFAULT 0,
    s_ass   INTEGER NOT NULL DEFAULT 0,
    s_ann   INTEGER NOT NULL DEFAULT 0,
    s_srt   INTEGER NOT NULL DEFAULT 0,
    s_lng   INTEGER NOT NULL DEFAULT 0,
    -- Additive assembly-composition (data-model enrichment): genome assemblies
    -- by level + reference-genome count. Filled by the same explode->sum rollup;
    -- mirrors eukahub_core.metrics.COMPOSITION_COLUMNS.
    n_ass_complete   INTEGER NOT NULL DEFAULT 0,
    n_ass_chromosome INTEGER NOT NULL DEFAULT 0,
    n_ass_scaffold   INTEGER NOT NULL DEFAULT 0,
    n_ass_contig     INTEGER NOT NULL DEFAULT 0,
    n_reference      INTEGER NOT NULL DEFAULT 0
);

-- Quality stats of each clade over the records on or below it, computed at build
-- time by fanning every record out to its ancestors (medians are not additive, so
-- they come from the records, never from the children). One row per clade with at
-- least one record; a NULL means none of its records has that value. Columns
-- mirror eukahub_core.metrics.QUALITY_STATS keys. Stats of a set of clades
-- (include minus exclude) are still computed per request from the record tables.
CREATE TABLE IF NOT EXISTS clade_stats (
    taxid        INTEGER PRIMARY KEY,
    busco        REAL,              -- best BUSCO complete % (max)
    genes        DOUBLE PRECISION,  -- median protein-coding gene count
    genome_size  DOUBLE PRECISION,  -- median assembly length (bp)
    contig_n50   DOUBLE PRECISION   -- median contig N50 (bp)
);

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
    download_url          TEXT,     -- NCBI Datasets page for the assembly
    -- Computed at build time:
    species_taxid         INTEGER NOT NULL,  -- taxid if a species, else the nearest one above
    annotations           INTEGER NOT NULL,  -- annotations of any version of the accession
    best_busco            REAL               -- best BUSCO complete % among them
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

-- RNA-Seq runs in ENA, counted per taxon, study, platform, submitting centre and
-- year of first release: about 8.5 million runs are too many to keep one by one.
-- One row per such group; like the record tables, no FK on taxid.
CREATE TABLE IF NOT EXISTS rna_seq_runs (
    taxid             INTEGER  NOT NULL,
    study_accession   TEXT,              -- the run's study (BioProject), in `study`
    long_read         BOOLEAN  NOT NULL, -- Oxford Nanopore or PacBio SMRT
    center_name       TEXT,              -- the submitting centre, as ENA spells it
    first_public_year SMALLINT,
    runs              INTEGER  NOT NULL,
    bases             BIGINT,            -- sum of the runs' base_count; null if none has one
    reads             BIGINT             -- sum of the runs' read_count; null if none has one
);
CREATE INDEX IF NOT EXISTS rna_seq_runs_taxid_idx ON rna_seq_runs (taxid);
CREATE INDEX IF NOT EXISTS rna_seq_runs_study_idx ON rna_seq_runs (study_accession);

-- The ENA studies (BioProjects) of those runs and their parents, to find runs by
-- project: a study's parents are the umbrella projects it belongs to (several
-- for some, such as a Darwin Tree of Life project under ERGA and the EBP).
CREATE TABLE IF NOT EXISTS study (
    study_accession TEXT   PRIMARY KEY,
    title           TEXT,
    parents         TEXT[] NOT NULL
);
CREATE INDEX IF NOT EXISTS study_title_trgm_idx ON study USING GIN (title gin_trgm_ops);

-- Dataset provenance: a single row stamped by the build at the very end, so the
-- app can show "Data updated <date>" and the record counts travel with the data
-- (a dump/restore carries the stamp). The one-row invariant is enforced by a
-- fixed primary key (the build TRUNCATEs + inserts id = TRUE). Absent/empty is a
-- valid state the API tolerates (serves built_at = null before the first build).
CREATE TABLE IF NOT EXISTS dataset_meta (
    id               BOOLEAN     PRIMARY KEY DEFAULT TRUE CHECK (id),  -- single row
    built_at         TIMESTAMPTZ NOT NULL,   -- when this dataset finished building (UTC)
    taxon_count      INTEGER     NOT NULL DEFAULT 0,
    assembly_count   INTEGER     NOT NULL DEFAULT 0,
    annotation_count INTEGER     NOT NULL DEFAULT 0,
    clade_count      INTEGER     NOT NULL DEFAULT 0
);
