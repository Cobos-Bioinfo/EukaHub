# Deployment and operations

How to run EukaHub in production and keep it running. The short version: bring
the stack up with Docker Compose; it installs the dataset by itself and keeps it
current from the repository's monthly Releases. For how the pieces fit together,
see [architecture.md](architecture.md).

## Requirements

- Docker Engine with the Compose v2 plugin.
- About 1 GB of RAM and one CPU core for the whole stack (tested under those limits).
- Disk: the database takes about 1 GB. During an update three copies exist for a
  few minutes (live, incoming, previous), so plan for about 3 GB plus the images.
- Outbound HTTPS to `api.github.com` and `github.com` (the Release download
  redirects to GitHub's asset storage). No inbound access is needed besides the web
  port.

## Install

```bash
git clone https://github.com/Cobos-Bioinfo/EukaHub.git
cd EukaHub
cp infra/.env.example infra/.env
sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(openssl rand -hex 24)/" infra/.env
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env up --build -d
```

The web app is on port 8080. The database starts empty; the `refresher` service
downloads the latest dataset Release (about 50 MB), restores and verifies it, and
swaps it in. This takes a few minutes on one core, during which data pages answer
"not found". Follow it with:

```bash
docker compose -f infra/docker-compose.prod.yml logs -f refresher
```

`POSTGRES_PASSWORD` is applied only when the database volume is first created.
To change it later, either recreate the volume (`down -v`, then `up`; the dataset
reinstalls itself) or run `ALTER USER` inside the `db` container.

## Services

| Service | Image | Published | Purpose |
|---|---|---|---|
| `db` | `postgres:17` | no | Serving database. Parallel workers and JIT disabled for a one-core host. |
| `api` | built from `api/Dockerfile` | no | FastAPI on port 8000, reached only through `web`. |
| `web` | built from `web/Dockerfile.prod` | `8080` | nginx: the SPA, the `/api` proxy and a response cache. |
| `refresher` | built from `infra/refresher.Dockerfile` | no | Installs and updates the dataset. |

All services restart automatically (`restart: unless-stopped`) and rotate their logs
(three files of 10 MB each).

## Configuration

Set in `infra/.env` (see `infra/.env.example`). All are optional except
`POSTGRES_PASSWORD`: the stack refuses to start without it.

| Variable | Default | Used by | Meaning |
|---|---|---|---|
| `POSTGRES_PASSWORD` | none (required) | db, api, refresher | Database password. Letters and digits only, since it is embedded in a connection URL. |
| `POSTGRES_USER` / `POSTGRES_DB` | `eukahub` | db, api, refresher | Database user and name. |
| `EUKAHUB_REPO` | `Cobos-Bioinfo/EukaHub` | refresher | Repository whose dataset Releases are installed (`owner/name`). |
| `REFRESH_INTERVAL` | `86400` | refresher | Seconds between checks for a newer Release. |
| `DB_STATEMENT_TIMEOUT_MS` | `15000` | api | Postgres cancels any API query slower than this; the client gets a 504. Keep it below nginx's 60 s proxy timeout. |
| `DB_POOL_MAX` | `4` | api | Most database connections the API holds. Raise only with more CPU cores. |
| `EXPORT_BATCH_ROWS` | `5000` | api | Rows per chunk of a TSV download, 1000 to 10000. Larger is slightly faster and costs about 1 MB of API memory per 1,000 rows, for each download running at once. An invalid value is logged and the default is used. |
| `CACHE_MAX_AGE` | `3600` | api | Seconds that browsers and the nginx cache may reuse a response. |
| `CORS_ALLOW_ORIGINS` | `http://localhost:8080` | api | Comma-separated origins allowed to call the API from another site. The bundled SPA calls it same-origin and does not need this. |
| `LOG_LEVEL` | `INFO` | api | Python log level; logs are JSON lines on stdout. |

### Links, contact and Wikipedia

These change what the site shows without rebuilding anything: set them in
`infra/.env`, then recreate the API container with `$C up -d api` (`$C` is defined
under [Data updates](#data-updates)). Browsers and the nginx cache may keep the old
values for up to `CACHE_MAX_AGE` seconds. An invalid value does not stop the API: it logs a warning
naming the variable (`ignoring FEEDBACK_URL (...)`) and uses the default. Every link
must be an `https://` URL.

| Variable | Default | Meaning |
|---|---|---|
| `ASSEMBLY_LINK_TEMPLATE` | NCBI Datasets genome search | "Open at the source" link for assemblies. Must contain `{taxid}`, which is replaced by the taxon's id. |
| `ANNOTATION_LINK_TEMPLATE` | Annotrieve annotation search | The same for annotations. |
| `RNA_SEQ_LINK_TEMPLATE` / `LONG_READ_LINK_TEMPLATE` | ENA advanced searches | The same for RNA-Seq and long-read RNA-Seq runs. The defaults are in `core/src/eukahub_core/metrics.py`. |
| `FEEDBACK_URL` | the EukaHub Google Form | "Send feedback" in the header menu. |
| `SOURCE_CODE_URL` | `https://github.com/Cobos-Bioinfo/EukaHub` | The GitHub icon in the header. |
| `PRIVACY_CONTACT_EMAIL` | `placeholder@crg.eu` | Data protection contact on the Privacy page. Set it to the address of whoever runs the server. |
| `WIKIPEDIA_SUMMARY_URL` | `https://en.wikipedia.org/api/rest_v1/page/summary/{title}` | Where the "About" summaries come from. Must contain `{title}`. |
| `WIKIPEDIA_USER_AGENT` | `EukaHub/1.0 (<SOURCE_CODE_URL>)` | Sent with every Wikipedia request. Wikipedia asks for one that says how to reach the operator. |
| `WIKIPEDIA_TIMEOUT_SECONDS` | `6` | How long a summary lookup may take, 1 to 30 seconds. |

### Curated groups

The groups with a friendly name ("Mammals" rather than "Mammalia"), the pool that
"Surprise me" picks from, and the cards under "Featured groups" on the landing page
come from `infra/config/groups.json`. Without that file the API uses the built-in
list, which is also in `infra/config/groups.example.json`. To change it:

```bash
cp infra/config/groups.example.json infra/config/groups.json
# edit infra/config/groups.json
$C restart api
```

```json
{
  "groups": [
    {"taxid": 40674, "label": "Mammals", "featured": true},
    {"taxid": 9443, "label": "Primates"}
  ]
}
```

- `taxid`: an NCBI taxon id. A group that is not in the dataset is skipped.
- `label`: the name shown on the site, 1 to 60 characters.
- `featured` (optional): `true` puts the group on the landing page. Featured groups
  appear in file order; at most 12.

The file holds 1 to 100 groups, each taxid once. If it cannot be read or breaks any
of these rules, the API logs a warning that says why and uses the built-in list.

## Behind a reverse proxy (TLS)

The stack serves plain HTTP on port 8080 and expects TLS to be terminated in front
of it (Traefik, nginx, Caddy, ...). Recommended:

- Do not expose 8080 to the internet directly: attach `web` to the proxy's Docker
  network and remove its `ports:` mapping, or bind it to `127.0.0.1:8080:80`.
- Route all paths (`/` and `/api/`) to `web`; it proxies the API itself.
- Add at the proxy: HSTS, and a Content-Security-Policy. The dashboard shows
  Wikipedia thumbnails, so `img-src` must allow `https://thumb.wikimedia.org`
  (and `https://upload.wikimedia.org`). A starting point:
  `default-src 'self'; img-src 'self' https://thumb.wikimedia.org https://upload.wikimedia.org; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'`.
- Rate limiting is built in: `web` allows each client about 10 API requests per
  second. Bursts of up to 20 pass at once, larger ones are slowed down, and past 60
  they are refused with 429. The client address comes from `X-Forwarded-For` when
  the request arrives from a private network, which covers a proxy on the same
  Docker network. If a proxy or load balancer with a public address sits in front,
  add it to the `set_real_ip_from` lines in `web/nginx.conf`; otherwise every
  visitor shares a single limit.

The app itself already sends `X-Content-Type-Options`, `X-Frame-Options` and
`Referrer-Policy`.

## Data updates

The refresher checks once a day for a newer `dataset-YYYYMMDD` Release of
`EUKAHUB_REPO` and installs it (details in [architecture.md](architecture.md#data-updates)).
It logs every decision:

- `up to date (loaded ..., latest release ...)`: nothing to do.
- `installing dataset-...` then `now serving dataset-...`: an update went live.
- `refresh cycle failed`: the live data is unchanged; it retries in an hour.
- `skipping dataset-...: it failed to install 3 times`: that Release is bad; the
  site keeps the previous data until a newer Release is published.
- `dataset is N days old and no newer release exists`: the monthly rebuild has
  stopped producing Releases; check the Actions tab of `EUKAHUB_REPO`.

`GET /api/meta` returns the build date of the data being served (also shown in the
site footer).

Useful commands (run from the repository root; `C` is shorthand):

```bash
C="docker compose -f infra/docker-compose.prod.yml --env-file infra/.env"

# Check for a new Release now instead of waiting for the daily cycle
$C exec refresher uv run --no-sync --package eukahub-pipeline python scripts/auto_refresh.py --once

# Put the previous dataset back
$C exec refresher uv run --no-sync --package eukahub-pipeline python scripts/restore_snapshot.py --rollback
```

After a rollback the refresher will install the newer Release again on its next
cycle. To stay on the previous data, stop it (`$C stop refresher`) until a fixed
Release is published.

## Running from a fork

A fork can serve data in one of two ways:

1. **Use the upstream data.** Keep `EUKAHUB_REPO=Cobos-Bioinfo/EukaHub`. The fork
   needs no GitHub Actions at all; it installs the Releases the upstream repository
   publishes.
2. **Publish its own data.** Set `EUKAHUB_REPO=<org>/<repo>` and enable the rebuild
   in the fork:
   - Enable GitHub Actions in the fork (Actions tab). Scheduled workflows in a fork
     stay disabled until they are enabled explicitly.
   - The workflow requests `contents: write` (to publish Releases), `actions: write`
     (to keep its schedule enabled) and `issues: write` (to report a failed
     scheduled rebuild), each only in the job that needs it. If the organization
     caps workflow permissions, allow these under Settings → Actions → General.
   - Run "Dataset rebuild" once by hand (`gh workflow run rebuild.yml`, from the
     default branch) to publish the first Release; it then runs on the 1st of each
     month. A rebuild takes about 30 minutes on a GitHub-hosted runner. Only the
     default branch publishes: a run on another branch builds and keeps the dump as
     a workflow artifact, which is useful for testing pipeline changes.

GitHub disables scheduled workflows in public repositories after 60 days without
activity; `rebuild.yml` re-enables itself on every run to prevent that.

### Rebuild settings

If a data source moves, the rebuild can be pointed at the new address without a
commit: add a repository variable under Settings → Secrets and variables → Actions →
Variables (organization variables work too). These are variables, not secrets: the
values are public, and GitHub hides secrets in the logs, which would also hide the
address a build actually used. An unset variable keeps the default, and each build
logs the values it uses. An invalid value (a URL that is not `https://`, a timeout
that is not a positive number) stops the build before it downloads anything, so
nothing is published.

| Variable | Default |
|---|---|
| `TAXDUMP_URL` | `https://ftp.ncbi.nlm.nih.gov/pub/taxonomy/taxdump.tar.gz` |
| `ENA_PORTAL_URL` | `https://www.ebi.ac.uk/ena/portal/api` |
| `ANNOTRIEVE_API_URL` | `https://genome.crg.es/annotrieve/api/v0` |
| `TAXDUMP_TIMEOUT_SECONDS` / `ENA_TIMEOUT_SECONDS` / `ANNOTRIEVE_TIMEOUT_SECONDS` | `120` / `300` / `600` (per request) |
| `NCBI_DATASETS_CLI_URL` | `https://ftp.ncbi.nlm.nih.gov/pub/datasets/command-line/v2/linux-amd64/datasets` |

The same variables, set in the environment, apply to a local
`python -m eukahub_pipeline.build`. The defaults live in
`pipeline/src/eukahub_pipeline/sources.py`.

## Updating the application

```bash
git pull
$C up --build -d
```

Base images (`postgres:17`, `nginx:alpine`, `python:3.13-slim`) receive security
fixes over time; rebuild with `$C build --pull && $C up -d` every few months.

## Health checks and troubleshooting

- `GET /healthz` (nginx), `GET /api/health` (API process), `GET /api/health/ready`
  (API can reach the database). Compose uses these for container health.
- Data pages say "not found" right after the first start: the dataset is still
  installing; see the refresher logs.
- A request returns 504 "needs more work than the server allows": a very large
  query hit the time limit. The server is unaffected; a smaller group or a coarser
  rank works.
- 503 "The server is busy": all database connections were busy; clients should
  retry after the `Retry-After` delay.

## Testing under the production budget

`infra/lowmem-test/` runs the whole stack capped at 1 GB of RAM (no swap) with every
container pinned to one CPU core, installs the dataset, and times typical and
heavy requests (such as exporting every eukaryotic species):

```bash
sudo bash infra/lowmem-test/lowmem-test.sh "$PWD"
```

It deletes the prod stack's database volume first (`down -v`), and ends with the
refresher's install log and the command that tears the test stack down. The test stack
has no `infra/.env`, so compose commands run against it by hand need `POSTGRES_PASSWORD`
set to any value, as in that command.
