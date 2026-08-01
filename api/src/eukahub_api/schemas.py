"""API response models — derived from the metric config so they can't drift.

The static card chrome (titles, help text, colors, external URLs) lives in
``eukahub_core.metrics.METRICS`` and is served once via ``/metrics-config``.
These per-clade payloads carry only the numbers, keyed by metric key
("ass", "ann", "rna", "lng"), so the frontend loops the metric config to
render one card per resource.
"""

from __future__ import annotations

from eukahub_core.metrics import METRIC_KEYS, CladeMetadata, Metric
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
        )


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
