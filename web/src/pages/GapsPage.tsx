import { Link, useSearchParams } from "react-router";

import { getGaps, getMetricsConfig, getQualityConfig } from "../api/queries";
import type { GapItem, MetricFilter, QualityStatConfig, TargetRank } from "../api/types";
import GapsScatter from "../components/GapsScatter";
import RootPicker from "../components/RootPicker";
import { DashboardIcon, MapIcon, TreeIcon } from "../components/icons";
import { useAsync } from "../hooks/useAsync";
import { cladeLabel } from "../lib/clades";
import { fmt, fmtCompact, fmtPct, fmtQuality } from "../lib/format";

const EUKARYOTA_TAXID = 2759;

// Ranks the leaderboard can group by (species excluded — a species is one row,
// so its "gap" is 0 or 1 and meaningless). Coarse → fine, the selector order.
const RANKS: TargetRank[] = ["phylum", "class", "order", "family", "genus"];
const RESOURCES: MetricFilter[] = ["ass", "ann", "rna", "lng"];
// One step finer, for the "look inside" re-root that walks down the tree.
const FINER: Record<string, TargetRank> = {
  phylum: "class",
  class: "order",
  order: "family",
  family: "genus",
  genus: "genus",
};
const PLURAL: Record<string, string> = {
  phylum: "phyla",
  class: "classes",
  order: "orders",
  family: "families",
  genus: "genera",
};

/** "Where are the gaps?" — the app's thesis surfaced directly. Ranks the biggest
 *  under-sequenced groups (most species with no data for a chosen resource) at a
 *  chosen rank under a chosen root. Root/rank/resource live in the URL, so a view
 *  is shareable. Reuses the breakdown machinery server-side (one ltree query). */
export default function GapsPage() {
  const [params, setParams] = useSearchParams();
  const root = Number(params.get("root")) || EUKARYOTA_TAXID;
  const rawRank = params.get("rank") as TargetRank;
  const rank: TargetRank = RANKS.includes(rawRank) ? rawRank : "order";
  const rawRes = params.get("resource") as MetricFilter;
  const resource: MetricFilter = RESOURCES.includes(rawRes) ? rawRes : "ass";
  const view: "list" | "scatter" = params.get("view") === "scatter" ? "scatter" : "list";

  const patch = (next: Record<string, string>) => {
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) p.set(k, v);
    setParams(p);
  };

  const metrics = useAsync(getMetricsConfig, []);
  const quality = useAsync(getQualityConfig, []);
  const gaps = useAsync(
    () => getGaps({ root, rank, resource, limit: 25 }),
    [root, rank, resource],
  );

  const resourceLabel = metrics.data?.find((m) => m.key === resource)?.card_title ?? "data";
  const resourceLower = resourceLabel.toLowerCase();
  // The surfaced quality figures (best BUSCO, median coding genes) shown next to
  // each gap: the quality of the data that *does* exist.
  const headlineQ = (quality.data ?? []).filter((q) => q.headline);
  const items = gaps.data?.items ?? [];
  const rootName = gaps.data ? (cladeLabel(gaps.data.root.taxid) ?? gaps.data.root.name) : "…";
  const maxGap = items.length ? items[0].gap : 1; // items are sorted gap-desc

  return (
    <section className="gaps">
      <header className="gaps__head">
        <h1 className="gaps__title">Where are the gaps?</h1>
        <p className="gaps__lede">
          The biggest groups with the least genomic data. Each is ranked by the number of species
          that still have no {resourceLower}, so a huge, barely-sequenced group rises to the top.
        </p>
      </header>

      <div className="gaps__controls">
        <div className="gaps__control gaps__control--search">
          <span className="gaps__control-label">Look under</span>
          <div className="gaps__root">
            <Link to={`/clade/${root}`} className="gaps__root-name">
              {rootName}
            </Link>
            {root !== EUKARYOTA_TAXID && (
              <button
                type="button"
                className="gaps__reset"
                onClick={() => patch({ root: String(EUKARYOTA_TAXID) })}
              >
                Reset to Eukaryota
              </button>
            )}
          </div>
          <RootPicker
            onPick={(t) => patch({ root: String(t.taxid) })}
            placeholder="Search a group to look within"
          />
        </div>

        <label className="gaps__control">
          <span className="gaps__control-label">Resource</span>
          <select
            className="control__select"
            value={resource}
            onChange={(e) => patch({ resource: e.target.value })}
          >
            {(metrics.data ?? []).map((m) => (
              <option key={m.key} value={m.key}>
                {m.card_title}
              </option>
            ))}
          </select>
        </label>

        <label className="gaps__control">
          <span className="gaps__control-label">Group by</span>
          <select
            className="control__select"
            value={rank}
            onChange={(e) => patch({ rank: e.target.value })}
          >
            {RANKS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
      </div>

      {gaps.error && <p className="notice notice--error">{gaps.error}</p>}
      {gaps.loading && !gaps.data && <p className="gaps__status">Loading…</p>}

      {gaps.data && items.length === 0 && (
        <p className="gaps__status">
          No {resourceLower} gaps at the {rank} level under {rootName}. Every group here is fully
          covered, or has no {rank}-level subgroups.
        </p>
      )}

      {items.length > 0 && (
        <>
          <div className="gaps__toolbar">
            <p className="gaps__summary">
              The {items.length} {PLURAL[rank]} with the most species missing {resourceLower}, of{" "}
              {fmt(gaps.data!.total_matches)} with a gap.
            </p>
            <div className="tree-controls__seg gaps__view" role="group" aria-label="View">
              <button
                type="button"
                className={`seg-btn${view === "list" ? " seg-btn--on" : ""}`}
                aria-pressed={view === "list"}
                onClick={() => patch({ view: "list" })}
              >
                List
              </button>
              <button
                type="button"
                className={`seg-btn${view === "scatter" ? " seg-btn--on" : ""}`}
                aria-pressed={view === "scatter"}
                onClick={() => patch({ view: "scatter" })}
              >
                Scatter
              </button>
            </div>
          </div>

          {view === "scatter" ? (
            <GapsScatter items={items} resourceLower={resourceLower} qstats={quality.data ?? []} />
          ) : (
            <ol className="gaps-lead">
              {items.map((it, i) => (
                <GapRow
                  key={it.taxid}
                  item={it}
                  idx={i}
                  maxGap={maxGap}
                  resourceLower={resourceLower}
                  headlineQ={headlineQ}
                  canLookInside={rank !== "genus"}
                  onLookInside={() => patch({ root: String(it.taxid), rank: FINER[rank] })}
                />
              ))}
            </ol>
          )}
        </>
      )}
    </section>
  );
}

/** One ranked group: rank number, name, a gap-magnitude bar (normalized to the
 *  top gap in view), the missing-species headline, coverage %, and cross-links. */
function GapRow({
  item,
  idx,
  maxGap,
  resourceLower,
  headlineQ,
  canLookInside,
  onLookInside,
}: {
  item: GapItem;
  idx: number;
  maxGap: number;
  resourceLower: string;
  headlineQ: QualityStatConfig[];
  canLookInside: boolean;
  onLookInside: () => void;
}) {
  const label = cladeLabel(item.taxid) ?? item.name;
  const width = Math.max((item.gap / maxGap) * 100, 2);
  // The quality of the genomes this clade *does* have (best BUSCO, median coding
  // genes). Null across the board means the covered species have no functional
  // annotation yet — itself part of the gap.
  const present = headlineQ
    .map((q) => ({ q, value: item.stats.find((s) => s.key === q.key)?.value ?? null }))
    .filter((s) => s.value !== null);
  return (
    <li className="gaps-row">
      <div className="gaps-row__num" aria-hidden="true">
        {idx + 1}
      </div>
      <div className="gaps-row__body">
        <div className="gaps-row__top">
          <Link to={`/clade/${item.taxid}`} className="gaps-row__name">
            {label}
          </Link>
          <span className="gaps-row__gap">
            <strong>{fmtCompact(item.gap)}</strong> missing
          </span>
        </div>
        <div
          className="gaps-row__bar"
          role="img"
          aria-label={`${fmt(item.gap)} of ${fmt(item.n_rows)} species have no ${resourceLower}`}
        >
          <div className="gaps-row__bar-fill" style={{ width: `${width}%` }} />
        </div>
        {headlineQ.length > 0 && (
          <div className="gaps-row__quality">
            <span className="gaps-row__qlabel">Where data exists</span>
            {present.length > 0 ? (
              present.map(({ q, value }) => (
                <span key={q.key} className="gaps-row__qstat">
                  {q.card_title} <strong>{fmtQuality(value, q.fmt)}</strong>
                </span>
              ))
            ) : (
              <span className="gaps-row__qstat gaps-row__qstat--none">No annotated genomes yet</span>
            )}
          </div>
        )}
        <div className="gaps-row__meta">
          <span className="gaps-row__stat">
            {fmt(item.n_rows)} species · {fmtPct(item.percent)}% covered
          </span>
          <span className="gaps-row__links">
            <Link to={`/clade/${item.taxid}`} className="gaps-row__link">
              <DashboardIcon size={13} /> Dashboard
            </Link>
            <Link to={`/tree/${item.taxid}`} className="gaps-row__link">
              <TreeIcon size={13} /> Tree
            </Link>
            <Link to={`/map/${item.taxid}`} className="gaps-row__link">
              <MapIcon size={13} /> Map
            </Link>
            {canLookInside && (
              <button type="button" className="gaps-row__link gaps-row__inside" onClick={onLookInside}>
                Look inside →
              </button>
            )}
          </span>
        </div>
      </div>
    </li>
  );
}
