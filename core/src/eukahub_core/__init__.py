"""EukaHub shared domain model.

Re-exports the metric config (the single source of truth) so both the API
and the pipeline import from one place.
"""

from eukahub_core.metrics import (
    COVERAGE_KEYS,
    METRIC_KEYS,
    METRIC_NAMES,
    METRICS,
    PERCENT_KEYS,
    TOTAL_KEYS,
    CladeMetadata,
    Metric,
    clade_feature_columns,
)

__all__ = [
    "COVERAGE_KEYS",
    "METRICS",
    "METRIC_KEYS",
    "METRIC_NAMES",
    "PERCENT_KEYS",
    "TOTAL_KEYS",
    "CladeMetadata",
    "Metric",
    "clade_feature_columns",
]
