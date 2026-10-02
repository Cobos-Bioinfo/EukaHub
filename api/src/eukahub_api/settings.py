"""Deployment settings: external links, the Wikipedia lookup, the curated groups
and the custom groups, read once from the environment and the optional groups file.

Every setting has a default, so an empty environment serves the upstream
values. An invalid value is logged and replaced by its default rather than
stopping the API. The variables are documented in docs/deployment.md.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Annotated

from eukahub_core.config import check_https_url, check_seconds
from eukahub_core.metrics import METRICS
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from eukahub_api.schemas import CladeGroup, CustomGroup

log = logging.getLogger("eukahub.api.settings")

# Environment variable that overrides each metric's "open at the source" link.
LINK_TEMPLATE_VARS: dict[str, str] = {
    "ass": "ASSEMBLY_LINK_TEMPLATE",
    "ann": "ANNOTATION_LINK_TEMPLATE",
    "rna": "RNA_SEQ_LINK_TEMPLATE",
    "lng": "LONG_READ_LINK_TEMPLATE",
}

DEFAULT_FEEDBACK_URL = (
    "https://docs.google.com/forms/d/e/1FAIpQLSfEEOn9g8c1G14DLkRr9qlMQldLdibyVO7zotzkIT4PKYgMKQ/viewform"
)
DEFAULT_SOURCE_CODE_URL = "https://github.com/Cobos-Bioinfo/EukaHub"
DEFAULT_PRIVACY_CONTACT_EMAIL = "placeholder@crg.eu"
DEFAULT_WIKIPEDIA_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
DEFAULT_WIKIPEDIA_TIMEOUT_SECONDS = 6.0
# A lookup holds a pooled database connection while it waits.
MAX_WIKIPEDIA_TIMEOUT_SECONDS = 30.0
# Rows per TSV export chunk. A batch costs about 1 MB of API memory per 1,000
# rows, for each export running at once.
DEFAULT_EXPORT_BATCH_ROWS = 5000
EXPORT_BATCH_ROWS_RANGE = (1000, 10000)

MAX_GROUPS = 100
MAX_FEATURED_GROUPS = 12
MAX_CUSTOM_GROUPS = 100

DEFAULT_GROUPS: tuple[CladeGroup, ...] = tuple(
    CladeGroup(taxid=taxid, label=label, featured=featured)
    for taxid, label, featured in (
        (9443, "Primates", False),
        (40674, "Mammals", True),
        (8782, "Birds", True),
        (9989, "Rodents", False),
        (9397, "Bats", False),
        (9721, "Whales & dolphins", False),
        (7898, "Ray-finned fishes", True),
        (7777, "Sharks & rays", False),
        (8292, "Amphibians", False),
        (8509, "Lizards & snakes", False),
        (50557, "Insects", True),
        (7041, "Beetles", False),
        (7088, "Butterflies & moths", False),
        (7399, "Bees, wasps & ants", False),
        (7147, "Flies", False),
        (4751, "Fungi", True),
        (5204, "Mushroom fungi", False),
        (4891, "Yeasts", False),
        (33090, "Green plants", False),
        (3398, "Flowering plants", True),
        (4479, "Grasses", False),
        (4747, "Orchids", False),
        (3803, "Legumes", False),
        (6231, "Nematodes", False),
        (6447, "Molluscs", False),
        (6854, "Arachnids", False),
        (6683, "Crabs & shrimp", False),
        (6073, "Corals & jellyfish", False),
        (7586, "Echinoderms", False),
        (5794, "Apicomplexans", False),
        (5878, "Ciliates", False),
        (2836, "Diatoms", False),
    )
)

_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class GroupsFile(BaseModel):
    """The groups file: ``{"groups": [{"taxid", "label", "featured"?}, ...],
    "custom_groups"?: [{"id", "label", "include"?, "exclude"?, "parent"?, "rest"?}, ...]}``.
    Rules that need the taxonomy are checked per request (``clade_sets.py``)."""

    model_config = ConfigDict(extra="forbid")

    groups: Annotated[list[CladeGroup], Field(min_length=1, max_length=MAX_GROUPS)]
    custom_groups: Annotated[list[CustomGroup], Field(max_length=MAX_CUSTOM_GROUPS)] = []

    @model_validator(mode="after")
    def _check_groups(self) -> GroupsFile:
        taxids = [g.taxid for g in self.groups]
        if len(set(taxids)) != len(taxids):
            raise ValueError("each taxid may appear only once")
        if sum(g.featured for g in self.groups) > MAX_FEATURED_GROUPS:
            raise ValueError(f"at most {MAX_FEATURED_GROUPS} groups may be featured")
        return self

    @model_validator(mode="after")
    def _check_custom_groups(self) -> GroupsFile:
        parents = {g.id: g.parent for g in self.custom_groups}
        if len(parents) != len(self.custom_groups):
            raise ValueError("each custom group id may appear only once")
        for g in self.custom_groups:
            seen = {g.id}
            parent = g.parent
            while parent is not None:
                if parent not in parents:
                    raise ValueError(f"custom group {g.id!r} has an unknown parent {parent!r}")
                if parent in seen:
                    raise ValueError(f"custom group {g.id!r} is inside itself")
                seen.add(parent)
                parent = parents[parent]
        rest_parents = [g.parent for g in self.custom_groups if g.rest]
        if len(set(rest_parents)) != len(rest_parents):
            raise ValueError("a parent group may have only one rest group")
        return self


@dataclass(frozen=True, slots=True)
class Settings:
    link_templates: Mapping[str, str]  # metric key -> URL template with {taxid}
    feedback_url: str
    source_code_url: str
    privacy_contact_email: str
    wikipedia_summary_url: str  # URL template with {title}
    wikipedia_user_agent: str
    wikipedia_timeout_seconds: float
    export_batch_rows: int
    groups: tuple[CladeGroup, ...]
    custom_groups: tuple[CustomGroup, ...]

    @property
    def featured_taxids(self) -> tuple[int, ...]:
        return tuple(g.taxid for g in self.groups if g.featured)


def _check_email(value: str) -> str:
    if not _EMAIL.fullmatch(value):
        raise ValueError("must be an email address")
    return value


def _check_batch_rows(value: str) -> int:
    low, high = EXPORT_BATCH_ROWS_RANGE
    if not value.isdigit() or not low <= int(value) <= high:
        raise ValueError(f"must be a whole number from {low} to {high}")
    return int(value)


def _check_user_agent(value: str) -> str:
    if len(value) > 200 or not all(" " <= c <= "~" for c in value):
        raise ValueError("must be at most 200 printable ASCII characters")
    return value


def _setting[T](
    environ: Mapping[str, str], name: str, default: T, check: Callable[[str], T]
) -> T:
    """The checked value of ``name``, or ``default`` when it is unset, empty or
    invalid (logged)."""
    raw = environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return check(raw)
    except ValueError as e:
        log.warning("ignoring %s (%s); using the default", name, e)
        return default


def _load_groups(path: str) -> tuple[tuple[CladeGroup, ...], tuple[CustomGroup, ...]]:
    """The curated and custom groups in the file at ``path``, or the defaults (no
    custom groups) when no path is set or the file is missing or invalid (logged).
    Any invalid entry rejects the file."""
    defaults: tuple[tuple[CladeGroup, ...], tuple[CustomGroup, ...]] = (DEFAULT_GROUPS, ())
    if not path:
        return defaults
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        log.info("no groups file at %s; using the default groups", path)
        return defaults
    except OSError as e:
        log.warning("cannot read the groups file %s (%s); using the default groups", path, e)
        return defaults
    try:
        file = GroupsFile.model_validate_json(text)
    except ValidationError as e:
        problems = "; ".join(
            f"{'.'.join(map(str, err['loc'])) or 'file'}: {err['msg']}" for err in e.errors()[:3]
        )
        log.warning("ignoring the groups file %s (%s); using the default groups", path, problems)
        return defaults
    return tuple(file.groups), tuple(file.custom_groups)


def _url_check(placeholder: str | None = None) -> Callable[[str], str]:
    return lambda value: check_https_url(value, placeholder=placeholder)


def load_settings(environ: Mapping[str, str]) -> Settings:
    """Read every setting from ``environ`` and the groups file it names."""
    source_code_url = _setting(environ, "SOURCE_CODE_URL", DEFAULT_SOURCE_CODE_URL, _url_check())
    groups, custom_groups = _load_groups(environ.get("GROUPS_FILE", "").strip())
    return Settings(
        link_templates={
            m.key: _setting(
                environ, LINK_TEMPLATE_VARS[m.key], m.external_url_template, _url_check("{taxid}")
            )
            for m in METRICS
        },
        feedback_url=_setting(environ, "FEEDBACK_URL", DEFAULT_FEEDBACK_URL, _url_check()),
        source_code_url=source_code_url,
        privacy_contact_email=_setting(
            environ, "PRIVACY_CONTACT_EMAIL", DEFAULT_PRIVACY_CONTACT_EMAIL, _check_email
        ),
        wikipedia_summary_url=_setting(
            environ, "WIKIPEDIA_SUMMARY_URL", DEFAULT_WIKIPEDIA_SUMMARY_URL, _url_check("{title}")
        ),
        # Wikipedia asks for a User-Agent that says how to reach the operator.
        wikipedia_user_agent=_setting(
            environ, "WIKIPEDIA_USER_AGENT", f"EukaHub/1.0 ({source_code_url})", _check_user_agent
        ),
        wikipedia_timeout_seconds=_setting(
            environ,
            "WIKIPEDIA_TIMEOUT_SECONDS",
            DEFAULT_WIKIPEDIA_TIMEOUT_SECONDS,
            lambda v: check_seconds(v, maximum=MAX_WIKIPEDIA_TIMEOUT_SECONDS),
        ),
        export_batch_rows=_setting(
            environ, "EXPORT_BATCH_ROWS", DEFAULT_EXPORT_BATCH_ROWS, _check_batch_rows
        ),
        groups=groups,
        custom_groups=custom_groups,
    )


@cache
def get_settings() -> Settings:
    """The settings of this process, read once from ``os.environ``."""
    return load_settings(os.environ)
