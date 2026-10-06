#!/usr/bin/env bash
# Fresh install + realistic and heavy requests, whole stack capped at 1 GB RAM / 1 CPU core.
# Usage: sudo bash lowmem-test.sh /path/to/EukaHub-checkout
set -euo pipefail
REPO=$(cd "${1:?usage: lowmem-test.sh /path/to/EukaHub}" && pwd)
HERE=$(cd "$(dirname "$0")" && pwd)
# A throwaway stack, but the prod compose file still requires a password.
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-lowmemtest}"
C=(docker compose -f "$REPO/infra/docker-compose.prod.yml" -f "$HERE/lowmem.test.yml")
API=http://localhost:8080/api
echo "== Testing $REPO @ $(git -C "$REPO" rev-parse --short HEAD 2>/dev/null)$(git -C "$REPO" diff --quiet 2>/dev/null || echo ' + uncommitted changes')"

"${C[@]}" down -v
"${C[@]}" up --build -d

echo "== Waiting for the refresher to install the dataset (max 45 min)..."
start=$(date +%s)
until curl -fsS -o /dev/null "$API/taxons/2759" 2>/dev/null; do
  (( $(date +%s) - start > 2700 )) && { echo "Timed out"; "${C[@]}" logs --tail 40 refresher; exit 1; }
  sleep 15
done
echo "== Installed in $(( $(date +%s) - start ))s"

hit() {  # label, url  -> status, size, seconds (never aborts the script)
  printf "  %-40s %s\n" "$1" "$(curl -sS -o /dev/null -w "%{http_code}  %{size_download}B  %{time_total}s" "$2" 2>&1 || true)"
}

echo "== What the UI requests (expect 200, ideally well under 15s each)"
hit "overview (landing)"                  "$API/overview"
hit "gaps teaser (landing)"               "$API/gaps?limit=5&include_quality=false"
hit "summary Eukaryota (dashboard)"       "$API/taxons/2759"
hit "assemblies Eukaryota (records)"      "$API/assemblies?within=2759&limit=50"
hit "annotations Eukaryota (records)"     "$API/annotations?within=2759&limit=50"
hit "breakdown Eukaryota phylum (map)"    "$API/clade/2759/breakdown?rank=phylum&limit=250&exclude_empty=false"
hit "quality Eukaryota phylum (map)"      "$API/clade/2759/breakdown/quality?rank=phylum"
hit "quality Metazoa phylum (map)"        "$API/clade/33208/breakdown/quality?rank=phylum"
hit "quality Insecta order (map)"         "$API/clade/50557/breakdown/quality?rank=order"
hit "children Eukaryota (tree)"           "$API/taxon/2759/children?limit=100"
hit "gaps order (gaps page)"              "$API/gaps?rank=order&limit=25"
hit "compare 6 groups"                    "$API/compare?taxids=40674,8782,50557,4751,33090,7898"
hit "export Eukaryota phylum (download)"  "$API/clade/2759/export.tsv?rank=phylum"

echo "== Heaviest requests (expect 200 within seconds; a clean 504 after ~15s is acceptable, a hang or a crash is not)"
hit "quality Eukaryota genus"             "$API/clade/2759/breakdown/quality?rank=genus"
hit "export every eukaryote species"      "$API/clade/2759/export.tsv?rank=species"

echo "== Six different requests at once (expect all 200, slower than alone)"
hit "quality Metazoa genus"   "$API/clade/33208/breakdown/quality?rank=genus" &
hit "quality Fungi genus"     "$API/clade/4751/breakdown/quality?rank=genus" &
hit "gaps family"             "$API/gaps?rank=family&limit=200" &
hit "export Insecta species"  "$API/clade/50557/export.tsv?rank=species" &
hit "summary Mammalia"        "$API/taxons/40674" &
hit "children Metazoa"        "$API/taxon/33208/children?limit=100" &
wait

echo "== Orphaned queries: anything still running >20s after its request ended (expect none)"
docker exec eukahub-prod-db-1 psql -U "${POSTGRES_USER:-eukahub}" -d "${POSTGRES_DB:-eukahub}" -c \
  "select pid, now()-query_start as running, left(query,60) as query from pg_stat_activity
   where state='active' and pid<>pg_backend_pid() and now()-query_start > interval '20 seconds'"

echo "== Memory (peak includes reclaimable page cache; anon_now = the process's own memory)"
printf "  %-10s %9s %9s %11s %10s %9s\n" container peak_MB limit_MB anon_now_MB oom_kills restarts
for c in db api web refresher; do
  n=eukahub-prod-$c-1
  cg() { docker exec "$n" sh -c "$1"; }
  peak=$(cg 'cat /sys/fs/cgroup/memory.peak')
  lim=$(cg 'cat /sys/fs/cgroup/memory.max')
  anon=$(cg "awk '\$1==\"anon\"{print \$2}' /sys/fs/cgroup/memory.stat")
  oom=$(cg "awk '\$1==\"oom_kill\"{print \$2}' /sys/fs/cgroup/memory.events")
  rc=$(docker inspect -f '{{.RestartCount}}' "$n")
  printf "  %-10s %9d %9d %11d %10s %9s\n" "$c" $((peak/1000000)) $((lim/1000000)) $((anon/1000000)) "$oom" "$rc"
done

echo "== Database size on disk"
docker exec eukahub-prod-db-1 psql -U "${POSTGRES_USER:-eukahub}" -d "${POSTGRES_DB:-eukahub}" -tAc \
  "select datname, pg_size_pretty(pg_database_size(datname)) from pg_database where datname like 'eukahub%'"

echo "== Refresher install (expect analyzed, all invariants passed, promoted)"
"${C[@]}" logs --no-log-prefix refresher 2>&1 | grep -E "analyzed|invariants passed|promoted|ERROR|Error" || true

# The compose file refuses to load without POSTGRES_PASSWORD; any value does for `down`.
echo "== Done. Tear down with:"
echo "   sudo env POSTGRES_PASSWORD=x docker compose -f $REPO/infra/docker-compose.prod.yml -f $HERE/lowmem.test.yml down -v"
