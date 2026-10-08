"""The taxonomy download retries a dropped connection like the other sources."""

from __future__ import annotations

import io
import tarfile
from typing import Self

import requests
from eukahub_pipeline import download
from eukahub_pipeline.download import download_taxdump
from eukahub_pipeline.sources import Source
from tenacity import wait_none

SOURCE = Source("https://ftp.example.org/taxdump.tar.gz", 60)


def _archive() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name in ("nodes.dmp", "names.dmp", "merged.dmp"):
            data = f"{name}\n".encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class _Response:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        pass

    def raise_for_status(self) -> None:
        pass

    def iter_content(self, chunk_size: int):
        yield self.body


def test_a_dropped_download_is_retried(tmp_path, monkeypatch):
    calls: list[str] = []

    def get(url: str, **kwargs: object) -> _Response:
        calls.append(url)
        if len(calls) == 1:
            raise requests.ConnectionError("connection reset")
        return _Response(_archive())

    monkeypatch.setattr(download.requests, "get", get)
    monkeypatch.setattr(download, "_download", download._download.retry_with(wait=wait_none()))
    download_taxdump(tmp_path, SOURCE)
    assert calls == [SOURCE.url, SOURCE.url]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["names.dmp", "nodes.dmp"]
