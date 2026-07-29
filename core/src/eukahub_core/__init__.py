"""EukaHub shared domain model.

Re-exports the metric config (the single source of truth) so both the API
and the pipeline import from one place.
"""

from eukahub_core.metrics import (
    METRICS,
    METRIC_KEYS,
    COVERAGE_KEYS,
    TOTAL_KEYS,
    PERCENT_KEYS,
    Metric,
    CladeMetadata,
    clade_feature_columns,
)

__all__ = [
    "METRICS",
    "METRIC_KEYS",
    "COVERAGE_KEYS",
    "TOTAL_KEYS",
    "PERCENT_KEYS",
    "Metric",
    "CladeMetadata",
    "clade_feature_columns",
]
