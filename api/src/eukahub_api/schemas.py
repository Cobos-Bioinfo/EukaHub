"""API response models — derived from the metric config so they can't drift.

The static card chrome (titles, help text, colors, external URLs) lives in
``eukahub_core.metrics.METRICS`` and is served once via ``/metrics-config``.
These per-clade payloads carry only the numbers, keyed by metric key
("ass", "ann", "rna", "lng"), so the frontend loops the metric config to
render one card per resource.
"""

from __future__ import annotations

from eukahub_core.metrics import METRIC_KEYS, CladeMetadata
from pydantic import BaseModel


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
