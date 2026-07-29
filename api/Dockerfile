# EukaHub API image (Phase 0 scaffold).
# Build context is the repo root (see infra/docker-compose.yml) so uv can
# resolve the api member together with its workspace dependency, core.
FROM python:3.13-slim

# uv for dependency management.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY . .

# Install just the api member and its deps (incl. workspace core).
RUN uv sync --package eukahub-api --no-dev

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "--package", "eukahub-api", \
     "uvicorn", "eukahub_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
