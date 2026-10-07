"""``/config``: what a client reads once before showing any data."""

from collections.abc import Sequence

import psycopg
from eukahub_core.metrics import METRICS, QUALITY_STATS
from fastapi import APIRouter

from eukahub_api.clade_sets import resolve_groups, taxon_refs
from eukahub_api.db import Conn
from eukahub_api.queries import fetch_dataset_meta, fetch_set_taxa
from eukahub_api.schemas import (
    AppConfig,
    CustomGroup,
    CustomGroupItem,
    DatasetMeta,
    MetricConfig,
    QualityStatConfig,
)
from eukahub_api.settings import get_settings

router = APIRouter()


@router.get("/config", response_model=AppConfig)
def config(conn: Conn) -> AppConfig:
    """What a client reads once before showing any data: the dataset being served
    (``built_at`` is ``null`` before the first build has stamped the database), the
    presentation of each measure and quality stat, and the deployment's links,
    Wikipedia summary endpoint, curated groups and custom groups. Pass a custom
    group's clades to ``/taxons/aggregates`` for its data."""
    settings = get_settings()
    row = fetch_dataset_meta(conn)
    dataset = (
        DatasetMeta(
            built_at=None, taxon_count=0, assembly_count=0, annotation_count=0, clade_count=0
        )
        if row is None
        else DatasetMeta(
            built_at=row[0],
            taxon_count=row[1],
            assembly_count=row[2],
            annotation_count=row[3],
            clade_count=row[4],
        )
    )
    return AppConfig(
        dataset=dataset,
        metrics=[MetricConfig.from_metric(m, settings.link_templates[m.key]) for m in METRICS],
        quality_stats=[QualityStatConfig.from_stat(q) for q in QUALITY_STATS],
        feedback_url=settings.feedback_url,
        source_code_url=settings.source_code_url,
        privacy_contact_email=settings.privacy_contact_email,
        wikipedia_summary_url=settings.wikipedia_summary_url,
        groups=list(settings.groups),
        custom_groups=_custom_groups(conn, settings.custom_groups),
    )


def _custom_groups(
    conn: psycopg.Connection, groups: Sequence[CustomGroup]
) -> list[CustomGroupItem]:
    """The custom groups that fit the current taxonomy, each with its clades. A
    group that doesn't fit is left out and logged."""
    if not groups:
        return []
    order = dict.fromkeys(t for g in groups for t in g.include + g.exclude)
    taxa = fetch_set_taxa(conn, order)
    return [
        CustomGroupItem(
            id=r.group.id,
            label=r.group.label,
            parent=r.group.parent,
            rest=r.group.rest,
            include=taxon_refs((t for t in order if r.marks.get(t) is True), taxa),
            exclude=taxon_refs((t for t in order if r.marks.get(t) is False), taxa),
        )
        for r in resolve_groups(groups, taxa)
    ]
