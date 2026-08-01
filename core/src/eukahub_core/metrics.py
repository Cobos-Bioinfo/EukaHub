"""Single source of truth for the four resource metrics tracked per clade.

Ported from Euka-Survey's ``src/metrics.py`` and made framework-neutral —
the Streamlit-only presentation fields (named card color, material icon)
are dropped; everything here is either data-layer or plain UI copy the
React frontend can reuse.

The app and pipeline both reason about four genomic resources:

| key | card_title        | what it means                                  |
|-----|-------------------|------------------------------------------------|
| ass | Assemblies        | genome assemblies                              |
| ann | Annotations       | functional annotations of assemblies           |
| rna | RNA-Seq (Any)     | RNA-Seq runs, any sequencing platform          |
| lng | Long-Read RNA-Seq | RNA-Seq runs on Oxford Nanopore or PacBio SMRT |

Each resource produces three columns in ``clade_features``:

    c_<key>  species covered (>=1 of that resource)
    s_<key>  total resource count summed across the clade's species
    p_<key>  derived percentage (c_<key> / n_rows * 100), computed in code

To add or rename a metric, edit METRICS; every consumer (DB column set,
API responses, generated TS types) follows.
"""

from dataclasses import dataclass
from typing import Literal

Side = Literal["left", "right"]


@dataclass(frozen=True, slots=True)
class Metric:
    """A single tracked resource.

    Fields cover four concerns:

    - data layer: ``key`` drives the ``c_``/``s_``/``p_`` column suffixes.
    - bar chart: ``color``, ``side``, ``overlay``, ``legend_label`` define
      the divergent bar (left half = assemblies/annotations, right half =
      RNA-Seq runs; ``overlay=True`` is the darker overlaid metric in each
      pair). Kept for the eventual chart/Tree-of-Life views.
    - filter / sort controls: ``filter_label``, ``sort_count_label``,
      ``sort_total_label``.
    - summary card: ``card_title``, ``card_title_help``, ``species_help``,
      ``total_label``, ``total_help``, ``external_source_name``,
      ``external_url_template``.
    - TSV export: ``tsv_count_column``, ``tsv_total_column`` — the
      snake_case names in the public TSV schema.
    """

    key: str
    color: str
    side: Side
    overlay: bool
    legend_label: str
    filter_label: str
    sort_count_label: str
    sort_total_label: str
    card_title: str
    species_help: str
    total_label: str
    total_help: str
    external_source_name: str
    external_url_template: str
    tsv_count_column: str
    tsv_total_column: str
    # Optional — only `lng` carries a tooltip on the card title today.
    card_title_help: str | None = None

    @property
    def coverage_key(self) -> str:
        return f"c_{self.key}"

    @property
    def total_key(self) -> str:
        return f"s_{self.key}"

    @property
    def percent_key(self) -> str:
        return f"p_{self.key}"

    def external_url(self, taxid: int) -> str:
        """Return the per-taxon external link rendered in the card."""
        return self.external_url_template.format(taxid=taxid)


METRICS: tuple[Metric, ...] = (
    Metric(
        key="ass",
        color="#a6cee3",  # light blue
        side="left",
        overlay=False,
        legend_label="Assembled",
        filter_label="Assemblies",
        sort_count_label="Species with Assemblies",
        sort_total_label="Assemblies",
        card_title="Assemblies",
        species_help="Unique species with at least one genome assembly",
        total_label="Total Assemblies",
        total_help="Total number of genome assemblies across all species",
        external_source_name="NCBI",
        external_url_template="https://www.ncbi.nlm.nih.gov/datasets/genome/?taxon={taxid}",
        tsv_count_column="species_with_assemblies",
        tsv_total_column="total_assemblies",
    ),
    Metric(
        key="ann",
        color="#1f78b4",  # dark blue
        side="left",
        overlay=True,
        legend_label="Annotated",
        filter_label="Annotations",
        sort_count_label="Species with Annotations",
        sort_total_label="Annotations",
        card_title="Annotations",
        species_help="Unique species with at least one functional annotation",
        total_label="Total Annotations",
        total_help="Total number of annotated genomes across all species",
        external_source_name="Annotrieve",
        external_url_template="https://genome.crg.es/annotrieve/annotations/?taxids={taxid}",
        tsv_count_column="species_with_annotations",
        tsv_total_column="total_annotations",
    ),
    Metric(
        key="rna",
        color="#b2df8a",  # light green
        side="right",
        overlay=False,
        legend_label="RNA-Seq (Any)",
        filter_label="RNA-Seq (Any)",
        sort_count_label="Species with RNA-Seq (Any)",
        sort_total_label="RNA-Seq experiments (Any)",
        card_title="RNA-Seq (Any)",
        species_help="Unique species with any RNA-Seq read data",
        total_label="Total Runs",
        total_help="Total number of RNA-Seq runs across all species",
        external_source_name="ENA",
        external_url_template=(
            "https://www.ebi.ac.uk/ena/browser/advanced-search?"
            "result=read_run&query=tax_tree({taxid})%20AND%20"
            "(library_strategy%3D%22rna-seq%22%20OR%20library_source%3D%22TRANSCRIPTOMIC%22)&"
            "fields=run_accession%2Cexperiment_title%2Ctax_id%2Clibrary_strategy&limit=0"
        ),
        tsv_count_column="species_with_rna_seq",
        tsv_total_column="total_rna_seq",
    ),
    Metric(
        key="lng",
        color="#33a02c",  # dark green
        side="right",
        overlay=True,
        legend_label="Long-Read RNA",
        filter_label="Long-Read RNA",
        sort_count_label="Species with Long-Read RNA",
        sort_total_label="Long-Read RNA-Seq experiments",
        card_title="Long-Read RNA-Seq",
        card_title_help="RNA-Seq experiments performed with Oxford Nanopore or PacBio SMRT platforms",
        species_help="Unique species with at least one long-read RNA-Seq experiment",
        total_label="Total Runs",
        total_help="Total number of Long-Read RNA-Seq runs across all species",
        external_source_name="ENA",
        external_url_template=(
            "https://www.ebi.ac.uk/ena/browser/advanced-search?"
            "result=read_run&query=tax_tree({taxid})%20AND%20"
            "(library_strategy%3D%22rna-seq%22%20OR%20library_source%3D%22transcriptomic%22)%20AND%20"
            "(%20instrument_platform%3D%22oxford_nanopore%22%20OR%20instrument_platform%3D%22pacbio_smrt%22%20)&"
            "fields=run_accession%2Cexperiment_title%2Ctax_id%2Clibrary_strategy%2Cinstrument_platform&limit=0"
        ),
        tsv_count_column="species_with_long_read_rna_seq",
        tsv_total_column="total_long_read_rna_seq",
    ),
)


# Derived column tuples — most callers just want one of these.
METRIC_KEYS: tuple[str, ...] = tuple(m.key for m in METRICS)
COVERAGE_KEYS: tuple[str, ...] = tuple(m.coverage_key for m in METRICS)
TOTAL_KEYS: tuple[str, ...] = tuple(m.total_key for m in METRICS)
PERCENT_KEYS: tuple[str, ...] = tuple(m.percent_key for m in METRICS)


def clade_feature_columns() -> tuple[str, ...]:
    """The integer feature columns of ``clade_features`` in METRICS order.

    Single source that the schema (``infra/postgres/init/001_schema.sql``)
    mirrors and that the pipeline INSERT/COPY targets.
    """
    return COVERAGE_KEYS + TOTAL_KEYS


@dataclass(frozen=True, slots=True)
class CladeMetadata:
    """Typed per-taxon rollup from ``clade_features``.

    Field names mirror the SQL columns (``n_rows``, ``c_<key>``,
    ``s_<key>``) so dynamic lookup via ``getattr(meta, m.coverage_key)``
    keeps working for code that iterates METRICS. Percentages are derived
    on demand via ``percent(key)`` — not stored.
    """

    taxid: int
    n_rows: int
    c_ass: int
    c_ann: int
    c_rna: int
    c_lng: int
    s_ass: int
    s_ann: int
    s_rna: int
    s_lng: int

    def percent(self, key: str) -> float:
        """Coverage percentage ``c_<key> / n_rows * 100``.

        ``key`` is one of METRIC_KEYS ("ass", "ann", "rna", "lng").
        Returns 0.0 when ``n_rows == 0`` to avoid division by zero.
        """
        coverage: int = getattr(self, f"c_{key}")
        return (coverage / self.n_rows * 100) if self.n_rows else 0.0

    @classmethod
    def zero(cls, taxid: int) -> "CladeMetadata":
        """Zero-filled record for a taxon absent from ``clade_features``."""
        return cls(
            taxid=taxid,
            n_rows=0,
            c_ass=0,
            c_ann=0,
            c_rna=0,
            c_lng=0,
            s_ass=0,
            s_ann=0,
            s_rna=0,
            s_lng=0,
        )
