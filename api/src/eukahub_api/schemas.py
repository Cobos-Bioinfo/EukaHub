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
    resources: dict[str, ResourceSummary]  # keyed by metric key, in METRICS order

    @classmethod
    def from_metadata(cls, name: str, rank: str, meta: CladeMetadata) -> CladeSummary:
        return cls(
            taxid=meta.taxid,
            name=name,
            rank=rank,
            n_rows=meta.n_rows,
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


class Breakdown(BaseModel):
    """The breakdown (Q2) payload: a root's descendants at a target rank."""

    root: TaxonRef
    rank: str  # the target rank the root was broken down by
    total_matches: int  # taxa matching the filter, before `limit`
    returned: int  # rows actually included (== len(items) <= limit)
    items: list[CladeSummary]  # sorted, limited
