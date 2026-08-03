"""Print a Markdown summary of the current ``dataset_meta`` stamp.

Used by the scheduled rebuild to write a run summary ($GITHUB_STEP_SUMMARY);
handy locally to see what the serving DB currently holds. Reads ``DATABASE_URL``.

    DATABASE_URL=postgresql://... uv run python scripts/dataset_summary.py
"""

from __future__ import annotations

import os
from datetime import UTC

import psycopg

DEFAULT_URL = "postgresql://eukahub:eukahub@localhost:5432/eukahub"


def main() -> None:
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    with psycopg.connect(url) as conn:
        row = conn.execute(
            "SELECT built_at, taxon_count, assembly_count, annotation_count, clade_count "
            "FROM dataset_meta LIMIT 1"
        ).fetchone()
    if row is None:
        print("No dataset_meta row — the dataset has not been stamped.")
        return
    built_at, taxon, assembly, annotation, clade = row
    built = built_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    print("## Dataset rebuilt\n")
    print(f"- **Built at:** {built}")
    print(f"- **Taxa:** {taxon:,}")
    print(f"- **Assemblies:** {assembly:,}")
    print(f"- **Annotations:** {annotation:,}")
    print(f"- **Clade rollups:** {clade:,}")


if __name__ == "__main__":
    main()
