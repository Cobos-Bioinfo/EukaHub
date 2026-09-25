# EukaHub dataset refresher.
#
# Long-lived sidecar that installs the dataset on first start and picks up each
# monthly Release afterwards (see scripts/auto_refresh.py). Build context is the
# repo root so uv can resolve the pipeline member together with its workspace
# dependency, core.
#
# Based on the postgres image rather than a python one so that pg_restore is
# guaranteed to match the server's major version; a client older than the server
# cannot read its dumps. uv brings its own Python, so the base image's is
# irrelevant.
FROM postgres:17

# ca-certificates for HTTPS to api.github.com; uv downloads a managed Python.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY . .

ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python
RUN uv sync --package eukahub-pipeline --no-dev

# The base image's entrypoint starts a database server; this container only
# talks to one.
ENTRYPOINT []
CMD ["uv", "run", "--no-sync", "--package", "eukahub-pipeline", \
     "python", "scripts/auto_refresh.py"]
