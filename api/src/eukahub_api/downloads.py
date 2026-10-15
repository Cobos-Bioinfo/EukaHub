"""Streamed TSV downloads."""

import itertools
from collections.abc import Iterator

from fastapi.responses import StreamingResponse


def tsv_download(chunks: Iterator[str], filename: str) -> StreamingResponse:
    """A streamed TSV attachment of ``chunks``. The header and the first batch of
    rows are pulled now: that runs the query (its sort is the expensive part) before
    any byte is sent, so a statement timeout is a clean 504 instead of a 200 that
    stops mid-download. Not cached: a download runs to tens of MB, and nginx's
    cache is kept for the small responses the interface repeats."""
    head = list(itertools.islice(chunks, 2))
    return StreamingResponse(
        itertools.chain(head, chunks),
        media_type="text/tab-separated-values",
        headers={
            "Content-Disposition": f'attachment; filename="{filename.replace(" ", "_")}"',
            "Cache-Control": "no-store",
        },
    )
