"""API response models — derived from the metric config so they can't drift.

The static card chrome (titles, help text, colors, external URLs) lives in
``eukahub_core.metrics.METRICS`` and is served once via ``/metrics-config``.
These per-clade payloads carry only the numbers, keyed by metric key
("ass", "ann", "rna", "lng"), so the frontend loops the metric config to
render one card per resource.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from eukahub_core.metrics import (
    METRIC_KEYS,
    CladeMetadata,
    Metric,
    QualityStat,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    model_validator,
)


class MetricConfig(BaseModel):
    """Static per-resource card chrome — served once by ``/metrics-config`` and
    joined client-side to the numbers in each per-clade payload (by ``key``)."""

    key: str
    card_title: str
    card_title_help: str | None
    species_help: str
    total_label: str
    total_help: str
    empty_text: str  # shown instead of a zero count
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
    def from_metric(cls, m: Metric, external_url_template: str) -> MetricConfig:
        return cls(
            key=m.key,
            card_title=m.card_title,
            card_title_help=m.card_title_help,
            species_help=m.species_help,
            total_label=m.total_label,
            total_help=m.total_help,
            empty_text=m.empty_text,
            color=m.color,
            external_source_name=m.external_source_name,
            external_url_template=external_url_template,
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

    @classmethod
    def by_metric(cls, meta: CladeMetadata) -> dict[str, ResourceSummary]:
        """One summary per metric key, in METRICS order."""
        return {
            key: cls(
                covered=getattr(meta, f"c_{key}"),
                total=getattr(meta, f"s_{key}"),
                percent=round(meta.percent(key), 2),
            )
            for key in METRIC_KEYS
        }


class AssemblyComposition(BaseModel):
    """Additive assembly-composition counts for a clade (from ``clade_features``):
    genome assemblies split by level, plus the reference/representative count.
    Summed up the lineage like the s_* totals."""

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
    # True for below-species taxa (subspecies/strains/varietas/...): a single
    # unit (n_rows == 1) whose data also counts for its species. The frontend
    # renders these as leaf detail (resource counts + source links), not a clade
    # coverage summary.
    is_infraspecific: bool = False
    resources: dict[str, ResourceSummary]  # keyed by metric key, in METRICS order
    composition: AssemblyComposition  # assembly-level split + reference count
    # Species and finer taxa only: records attached to this taxon itself, keyed by
    # metric key; the rest of each total sits on the finer taxa below it.
    direct: dict[str, int] | None = None

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
            resources=ResourceSummary.by_metric(meta),
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


MAX_CLADES_PER_GROUP = 20

_Taxid = Annotated[StrictInt, Field(gt=0)]
_Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
_GroupId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=40)]
_Clades = Annotated[tuple[_Taxid, ...], Field(max_length=MAX_CLADES_PER_GROUP)]


class CladeGroup(BaseModel):
    """A curated group: its friendly label is shown wherever the group appears,
    it is in the "Surprise me" pool, and ``featured`` groups are the landing-page
    cards. Also the entry format of the deployment's groups file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    taxid: _Taxid
    label: _Label
    featured: StrictBool = False


class CustomGroup(BaseModel):
    """A custom group from the deployment's groups file: the clades in ``include``
    minus the clades inside them in ``exclude``. A ``rest`` group is instead
    everything in its ``parent`` group that the parent's other groups leave out."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: _GroupId
    label: _Label
    include: _Clades = ()
    exclude: _Clades = ()
    parent: _GroupId | None = None
    rest: StrictBool = False

    @model_validator(mode="after")
    def _check_clades(self) -> CustomGroup:
        if self.rest:
            if self.parent is None:
                raise ValueError("a rest group needs a parent")
            if self.include or self.exclude:
                raise ValueError("a rest group takes no include or exclude")
        elif not self.include:
            raise ValueError("include at least one taxid")
        taxids = self.include + self.exclude
        if len(set(taxids)) != len(taxids):
            raise ValueError("each taxid may appear only once in a group")
        return self


class SiteConfig(BaseModel):
    """Deployment settings the web app reads once per page load (served by
    ``/site-config``)."""

    feedback_url: str
    source_code_url: str
    privacy_contact_email: str
    groups: list[CladeGroup]


class DatasetMeta(BaseModel):
    """Dataset provenance for the "Data updated" stamp — when the served dataset
    was built and how many records it holds. ``built_at`` is ``null`` before the
    first build has stamped the DB, in which case the frontend omits the stamp."""

    built_at: datetime | None  # UTC build timestamp, or null before the first build
    taxon_count: int
    assembly_count: int
    annotation_count: int
    clade_count: int


class TaxonRef(BaseModel):
    """Minimal taxon reference (breadcrumb / breakdown root)."""

    taxid: int
    name: str
    rank: str


class SearchHit(TaxonRef):
    """A name-search result, with what the picker needs to tell look-alike names apart."""

    context: str | None = Field(
        description="Nearest class, phylum or kingdom above the taxon, to tell homonyms apart."
    )
    has_data: bool = Field(
        description="Whether any assembly, annotation or RNA-Seq run sits on the taxon or below it."
    )
    similar: bool = Field(
        description="True when no name contains the query and this is a close spelling instead."
    )


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


class QualityStatValue(BaseModel):
    """A quality stat computed live over a taxon's subtree records (median or
    max per QUALITY_STATS). ``value`` is ``null`` when the subtree has no records
    carrying that field."""

    key: str
    value: float | None


class GapItem(BaseModel):
    """One under-sequenced group in the "Where are the gaps?" leaderboard: its
    species count, its coverage for the chosen resource, and the ``gap`` = species
    with no such data (``n_rows - covered``). The frontend ranks/visualizes by
    ``gap`` (biggest hole first)."""

    taxid: int
    name: str
    rank: str
    n_rows: int  # species in the clade
    covered: int  # species with >=1 of the chosen resource (c_<resource>)
    percent: float  # covered / n_rows * 100 — the coverage %
    gap: int  # n_rows - covered — species missing the resource (the "gap")
    # Quality of the data that *does* exist in this clade (best BUSCO / median
    # coding genes / median genome size / N50), keyed like QUALITY_STATS. A value
    # is null when no record in the clade carries that field. Empty when the
    # quality dimension isn't computed.
    stats: list[QualityStatValue] = []


class Gaps(BaseModel):
    """The "Where are the gaps?" payload: the biggest under-sequenced groups at a
    rank under a root, ranked by missing species for one resource (served by
    ``/gaps``)."""

    root: TaxonRef
    rank: str  # the rank the root was broken down by
    resource: str  # the metric key the gap is measured for ("ass"/"ann"/...)
    total_matches: int  # clades with any gap, before `limit`
    returned: int  # rows actually included (== len(items) <= limit)
    items: list[GapItem]  # sorted by gap desc, limited


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
    headline: bool  # True for the figures shown beside each group on the Gaps page

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


class CompareGroup(BaseModel):
    """One group in the compare view: its species count, per-resource coverage,
    and live quality stats — enough to line several groups up side by side."""

    taxid: int
    name: str
    rank: str
    n_rows: int  # species in the subtree
    resources: dict[str, ResourceSummary]  # keyed by metric key, in METRICS order
    quality: list[QualityStatValue]  # BUSCO / genes / genome size / N50, QUALITY_STATS order


class Compare(BaseModel):
    """The compare payload: several groups' summaries lined up (served by
    ``/compare``). Unknown taxids are dropped, so ``groups`` may be shorter than
    the requested set."""

    groups: list[CompareGroup]


class Aggregate(BaseModel):
    """Species count, per-resource coverage and quality stats for a set of clades
    (served by ``/aggregate``): a taxon is in the set when the nearest listed
    clade above it (or the taxon itself) is in ``include``."""

    include: list[TaxonRef]
    exclude: list[TaxonRef]
    n_rows: int  # species in the set
    resources: dict[str, ResourceSummary]  # keyed by metric key, in METRICS order
    composition: AssemblyComposition
    quality: list[QualityStatValue]  # BUSCO / genes / genome size / N50, QUALITY_STATS order


class CustomGroupItem(BaseModel):
    """One custom group from the groups file. ``include`` and ``exclude`` are the
    clades it is made of, worked out from the parent's other groups for a
    ``rest`` group, so they can be passed to ``/aggregate`` as they are. A rest
    group with nothing left lists no clades."""

    id: str
    label: str
    parent: str | None  # id of the group it sits under
    rest: bool  # everything in the parent that the parent's other groups leave out
    include: list[TaxonRef]
    exclude: list[TaxonRef]


class CustomGroups(BaseModel):
    """The deployment's custom groups, in groups-file order (served by
    ``/custom-groups``). A group that doesn't fit the current taxonomy is left out."""

    groups: list[CustomGroupItem]
