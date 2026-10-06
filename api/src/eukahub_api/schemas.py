"""API response models — derived from the metric config so they can't drift.

The static card chrome (titles, help text, colors, external URLs) lives in
``eukahub_core.metrics.METRICS`` and is served once in ``/config``.
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
    QualityAgg,
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
    """Static per-resource card chrome — served once in ``/config`` and joined
    client-side to the numbers in each per-clade payload (by ``key``)."""

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
    """One resource's counts for a taxon, summed over the taxon and everything
    below it when the dataset is built."""

    covered: int = Field(description="Species on or below the taxon with at least one record.")
    total: int = Field(description="Records on or below the taxon, at any rank.")
    percent: float = Field(description="covered / n_rows * 100, or 0 when n_rows is 0.")

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
    """The genome assemblies on or below a taxon by assembly level, and how many
    are NCBI reference or representative genomes; summed when the dataset is
    built, like the resource totals."""

    complete: int
    chromosome: int
    scaffold: int
    contig: int
    reference: int = Field(description="Assemblies NCBI marks as reference or representative.")

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
    n_rows: int = Field(
        description="Species on or below the taxon (1 for a species or a finer taxon)."
    )
    is_infraspecific: bool = Field(
        False,
        description="Below a species (subspecies, strain, ...): one unit whose data also "
        "counts for its species.",
    )
    resources: dict[str, ResourceSummary] = Field(
        description="Per resource, keyed by the metric keys in /config."
    )
    composition: AssemblyComposition
    direct: dict[str, int] | None = Field(
        None,
        description="Species and finer taxa only: per resource, the records on the taxon "
        "itself; the rest of each total is on the taxa below it.",
    )

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


class QualityStatValue(BaseModel):
    """A quality stat of a taxon: the median or the maximum (see ``aggregation`` in
    ``/config``) of one field over the records on or below it."""

    key: str
    value: float | None = Field(description="Null when no record under the taxon has the field.")


# --- Quality dimension (per-record drill-down + live distribution stats) -----


class QualityStatConfig(BaseModel):
    """Static chrome for one quality stat — served once in ``/config`` and
    joined client-side to the per-taxon ``QualityStatValue`` by ``key``.
    The analogue of ``MetricConfig`` for the annotation/assembly-quality
    dimension (BUSCO %, gene count, genome size, N50)."""

    key: str
    source: str  # "assembly" | "annotation" — which per-record table it comes from
    aggregation: QualityAgg = Field(
        description="How the records' values are summarized: their median or their maximum."
    )
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
            aggregation=q.agg,
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


class Page(BaseModel):
    """One page of a list. Pass ``next`` or ``previous`` back as ``cursor`` (with
    the same sort) for the page after or before this one."""

    total: int  # matching rows across all pages
    limit: int
    next: str | None  # null on the last page
    previous: str | None  # null on the first page


class AssemblyPage(Page):
    results: list[AssemblyRecord]


class AnnotationPage(Page):
    results: list[AnnotationRecord]


class Taxon(CladeSummary):
    """One taxon: the object ``/taxons/{taxid}`` returns and ``/taxons`` lists. Its
    ancestors are in ``/taxons/{taxid}/ancestors`` and its quality stats in
    ``/taxons/{taxid}/stats``."""

    context: str | None = Field(
        description="Nearest class, phylum or kingdom above the taxon, to tell homonyms apart."
    )
    has_children: bool


class TaxonPage(Page):
    results: list[Taxon]


class TaxonStats(BaseModel):
    """The quality stats of one taxon: the object ``/taxons/{taxid}/stats`` returns
    and ``/taxons/stats`` lists."""

    taxid: int
    name: str
    stats: list[QualityStatValue] = Field(
        description="As in /taxons/{taxid}: computed per request from every record on or "
        "below the taxon; /config says which aggregation each one is."
    )


class TaxonStatsPage(Page):
    results: list[TaxonStats]


class Aggregate(BaseModel):
    """Species count, per-resource coverage and quality stats for a set of clades
    (served by ``/taxons/aggregates``): a taxon is in the set when the nearest listed
    clade above it (or the taxon itself) is in ``include``."""

    include: list[TaxonRef]
    exclude: list[TaxonRef]
    n_rows: int  # species in the set
    resources: dict[str, ResourceSummary]  # keyed by metric key, in METRICS order
    composition: AssemblyComposition
    stats: list[QualityStatValue] = Field(
        description="As for a taxon, over the records in the set."
    )


class AggregatePage(Page):
    results: list[Aggregate]


class CustomGroupItem(BaseModel):
    """One custom group from the groups file. ``include`` and ``exclude`` are the
    clades it is made of, worked out from the parent's other groups for a
    ``rest`` group, so they can be passed to ``/taxons/aggregates`` as they are. A rest
    group with nothing left lists no clades."""

    id: str
    label: str
    parent: str | None  # id of the group it sits under
    rest: bool  # everything in the parent that the parent's other groups leave out
    include: list[TaxonRef]
    exclude: list[TaxonRef]


class AppConfig(BaseModel):
    """What a client reads once before showing any data (served by ``/config``):
    the dataset it is looking at, how to present each measure, and the
    deployment's links and groups."""

    dataset: DatasetMeta
    metrics: list[MetricConfig]  # in METRICS order
    quality_stats: list[QualityStatConfig]  # in QUALITY_STATS order
    feedback_url: str
    source_code_url: str
    privacy_contact_email: str
    # Wikipedia REST summary URL with {title}; clients fetch the "About" text themselves.
    wikipedia_summary_url: str
    groups: list[CladeGroup]  # curated groups; ``featured`` ones are the landing-page cards
    # In groups-file order; a group that doesn't fit the current taxonomy is left out.
    custom_groups: list[CustomGroupItem]
