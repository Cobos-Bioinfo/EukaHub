"""API response models — derived from the metric config so they can't drift.

The static card chrome (titles, help text, colors, external URLs) lives in
``eukahub_core.metrics.METRICS`` and is served once via ``/metrics-config``.
These per-clade payloads carry only the numbers, keyed by metric key
("ass", "ann", "rna", "lng"), so the frontend loops the metric config to
render one card per resource.
"""

from __future__ import annotations

from datetime import date

from eukahub_core.metrics import (
    METRIC_KEYS,
    CladeMetadata,
    Metric,
    QualityStat,
)
from pydantic import BaseModel


class MetricConfig(BaseModel):
    """Static per-resource card chrome — served once by ``/metrics-config`` and
    joined client-side to the numbers in each per-clade payload (by ``key``)."""

    key: str
    card_title: str
    card_title_help: str | None
    species_help: str
    total_label: str
    total_help: str
    color: str
    external_source_name: str
    external_url_template: str  # contains "{taxid}"; the client substitutes
    coverage_column: str
    total_column: str
    # Labels for the breakdown (Q2) filter/sort controls — the metric config's
    # single source of truth so the frontend's control copy can't drift.
    filter_label: str  # resource-presence checkbox label
    sort_count_label: str  # label for sorting by c_<key> (species covered)
    sort_total_label: str  # label for sorting by s_<key> (summed total)
    # Divergent bar-chart layout (Q2 chart): which half of the mirrored bar the
    # metric occupies, whether it's the darker overlaid (subset) metric in its
    # pair, and the short label used in the chart legend.
    side: str  # "left" (assemblies/annotations) | "right" (RNA-Seq)
    overlay: bool  # True = darker metric drawn over its lighter pair-mate
    legend_label: str

    @classmethod
    def from_metric(cls, m: Metric) -> MetricConfig:
        return cls(
            key=m.key,
            card_title=m.card_title,
            card_title_help=m.card_title_help,
            species_help=m.species_help,
            total_label=m.total_label,
            total_help=m.total_help,
            color=m.color,
            external_source_name=m.external_source_name,
            external_url_template=m.external_url_template,
            coverage_column=m.coverage_key,
            total_column=m.total_key,
            filter_label=m.filter_label,
            sort_count_label=m.sort_count_label,
            sort_total_label=m.sort_total_label,
            side=m.side,
            overlay=m.overlay,
            legend_label=m.legend_label,
        )


class ResourceSummary(BaseModel):
    """Per-resource rollup for one clade."""

    covered: int  # c_<key>: species in the subtree with >=1 of this resource
    total: int  # s_<key>: resource count summed across the subtree
    percent: float  # covered / n_rows * 100 (0.0 when n_rows == 0)


class AssemblyComposition(BaseModel):
    """Additive assembly-composition counts for a clade (from ``clade_features``):
    genome assemblies split by level, plus the reference/representative count.
    Summed species-only up the lineage like the s_* totals."""

    complete: int
    chromosome: int
    scaffold: int
    contig: int
    reference: int  # assemblies with a refseq_category set

    @classmethod
    def from_metadata(cls, meta: CladeMetadata) -> AssemblyComposition:
        return cls(
            complete=meta.n_ass_complete,
            chromosome=meta.n_ass_chromosome,
            scaffold=meta.n_ass_scaffold,
            contig=meta.n_ass_contig,
            reference=meta.n_reference,
        )


class CladeSummary(BaseModel):
    """The Genomic Resource Summary (Q1) payload for one taxon."""

    taxid: int
    name: str
    rank: str
    n_rows: int  # species in the subtree
    # True for below-species taxa (subspecies/strains/varietas/...): the row
    # holds only this taxon's own directly-attached data (n_rows == 1) and is
    # never counted toward any ancestor. The frontend renders these as leaf
    # detail (own resource counts + source links), not a clade coverage summary.
    is_infraspecific: bool = False
    resources: dict[str, ResourceSummary]  # keyed by metric key, in METRICS order
    composition: AssemblyComposition  # assembly-level split + reference count

    @classmethod
    def from_metadata(
        cls, name: str, rank: str, meta: CladeMetadata, is_infraspecific: bool = False
    ) -> CladeSummary:
        return cls(
            taxid=meta.taxid,
            name=name,
            rank=rank,
            n_rows=meta.n_rows,
            is_infraspecific=is_infraspecific,
            resources={
                key: ResourceSummary(
                    covered=getattr(meta, f"c_{key}"),
                    total=getattr(meta, f"s_{key}"),
                    percent=round(meta.percent(key), 2),
                )
                for key in METRIC_KEYS
            },
            composition=AssemblyComposition.from_metadata(meta),
        )


class OverviewTotals(BaseModel):
    """Global "at a glance" totals across the eukaryotic tree (Eukaryota's
    rollup) — the live headline numbers on the landing page."""

    species: int  # eukaryotic species surveyed
    assemblies: int  # genome assemblies
    annotations: int  # functional annotations
    rna_seq: int  # RNA-Seq runs (any platform)
    long_read: int  # long-read RNA-Seq runs
    reference_genomes: int  # assemblies flagged reference/representative


class FeaturedClade(BaseModel):
    """One featured group on the landing page: its species count and how much of
    it is assembled/annotated. The frontend supplies the friendly display label
    (by taxid); ``name`` is the scientific name as a fallback."""

    taxid: int
    name: str
    species: int  # species in the subtree
    assemblies: int  # total genome assemblies in the subtree
    assembly_percent: float  # % of species with >=1 assembly
    annotation_percent: float  # % of species with >=1 annotation


class Overview(BaseModel):
    """Landing-page payload: global totals + a handful of featured groups, in one
    cacheable request (served by ``/overview``)."""

    totals: OverviewTotals
    featured: list[FeaturedClade]


class TaxonRef(BaseModel):
    """Minimal taxon reference (breadcrumb / breakdown root)."""

    taxid: int
    name: str
    rank: str


class TaxonLineage(BaseModel):
    """A taxon plus its root→node lineage (for the header breadcrumb)."""

    taxid: int
    name: str
    rank: str
    lineage: list[TaxonRef]  # root first, this taxon last (inclusive)


class TaxonNode(CladeSummary):
    """One node in the interactive tree: a taxon's summary metrics plus a
    ``has_children`` hint, so the UI can show an expand affordance for a node
    without a second round-trip to discover it's a leaf."""

    has_children: bool

    @classmethod
    def from_child(
        cls,
        name: str,
        rank: str,
        meta: CladeMetadata,
        has_children: bool,
        is_infraspecific: bool = False,
    ) -> TaxonNode:
        s = CladeSummary.from_metadata(name, rank, meta, is_infraspecific)
        return cls(
            taxid=s.taxid,
            name=s.name,
            rank=s.rank,
            n_rows=s.n_rows,
            is_infraspecific=s.is_infraspecific,
            resources=s.resources,
            composition=s.composition,
            has_children=has_children,
        )


class TaxonChildren(BaseModel):
    """A taxon's direct children (adjacency) for lazy-expanding the tree."""

    parent: TaxonRef
    total: int  # total children before limit/offset (for "load more")
    returned: int  # rows actually returned (== len(items) <= limit)
    items: list[TaxonNode]  # sorted by species count desc


class TaxonAbout(BaseModel):
    """Wikipedia summary for a taxon's "About" card (decorative, non-load-bearing).

    Sourced live from Wikipedia's REST summary endpoint and cached server-side.
    The endpoint returns ``null`` instead of this model when the taxon has no
    usable article, in which case the frontend simply omits the card.
    """

    title: str  # article title (may differ from the NCBI name via redirect)
    description: str  # short one-line descriptor ("" when Wikipedia has none)
    extract: str  # first-paragraph plain-text summary
    thumbnail: str | None  # image URL (upload.wikimedia.org), if any
    url: str  # canonical desktop article URL


class Breakdown(BaseModel):
    """The breakdown (Q2) payload: a root's descendants at a target rank."""

    root: TaxonRef
    rank: str  # the target rank the root was broken down by
    total_matches: int  # taxa matching the filter, before `limit`
    returned: int  # rows actually included (== len(items) <= limit)
    items: list[CladeSummary]  # sorted, limited


# --- Quality dimension (per-record drill-down + live distribution stats) -----


class QualityStatConfig(BaseModel):
    """Static chrome for one quality stat — served once by ``/quality-config``
    and joined client-side to the per-taxon ``QualityStatValue`` by ``key``.
    The analogue of ``MetricConfig`` for the annotation/assembly-quality
    dimension (BUSCO %, gene count, genome size, N50)."""

    key: str
    source: str  # "assembly" | "annotation" — which per-record table it comes from
    card_title: str
    help: str
    unit: str | None  # "%", "bp", "genes", ...
    fmt: str  # "percent" | "integer" | "basepairs" — how the frontend renders it
    headline: bool  # True for the surfaced annotation-quality figures

    @classmethod
    def from_stat(cls, q: QualityStat) -> QualityStatConfig:
        return cls(
            key=q.key,
            source=q.source,
            card_title=q.card_title,
            help=q.help,
            unit=q.unit,
            fmt=q.fmt,
            headline=q.headline,
        )


class QualityStatValue(BaseModel):
    """A quality stat computed live over a taxon's subtree records (median or
    max per QUALITY_STATS). ``value`` is ``null`` when the subtree has no records
    carrying that field."""

    key: str
    value: float | None


class AssemblyRecord(BaseModel):
    """One genome assembly (from the ``assembly`` table), for the drill-down list.
    Fields mirror the aliased SELECT so the endpoint builds it from a dict_row."""

    assembly_accession: str
    taxid: int
    organism: str  # scientific name at the record's taxid
    assembly_level: str | None
    contig_n50: int | None
    scaffold_n50: int | None
    total_sequence_length: int | None
    gc_percent: float | None
    refseq_category: str | None
    release_date: date | None
    submitter: str | None
    source_database: str | None
    bioprojects: list[str]
    download_url: str | None


class AnnotationRecord(BaseModel):
    """One functional annotation (from the ``annotation`` table), for the
    drill-down list — the Annotrieve-sourced BUSCO + gene metadata + GFF link."""

    annotation_id: str
    assembly_accession: str | None
    taxid: int
    organism: str
    source_database: str | None
    provider: str | None
    release_date: date | None
    gff_url: str | None
    gene_count: int | None
    protein_coding_count: int | None
    busco_complete: float | None
    busco_single_copy: float | None
    busco_duplicated: float | None
    busco_lineage: str | None


class BucketQuality(BaseModel):
    """Per-bucket quality stats for a rank breakdown — one entry per breakdown
    tile that carries records, keyed by its ``taxid``. Lets the "data map" colour
    tiles by BUSCO / median genes / median genome size / N50 (the frontend merges
    these into the breakdown by taxid). ``stats`` are keyed like ``QUALITY_STATS``;
    a value is ``null`` when that bucket has no record carrying the field."""

    taxid: int
    stats: list[QualityStatValue]


class AssemblyList(BaseModel):
    """Assemblies under a taxon: live assembly-quality stats + a paginated list."""

    root: TaxonRef
    total: int  # records in the subtree, before limit/offset
    returned: int
    stats: list[QualityStatValue]  # median genome size / contig N50
    items: list[AssemblyRecord]


class AnnotationList(BaseModel):
    """Annotations under a taxon: live annotation-quality stats + a paginated list."""

    root: TaxonRef
    total: int
    returned: int
    stats: list[QualityStatValue]  # best BUSCO, median protein-coding gene count
    items: list[AnnotationRecord]
