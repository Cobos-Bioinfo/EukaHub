import { Link, useNavigate, useSearchParams } from "react-router";

import { getGaps, getMetricsConfig, getQualityConfig, type GapItem } from "../api/queries";
import type { MetricFilter, QualityStatConfig, TargetRank } from "../api/types";
import GapsScatter from "../components/GapsScatter";
import { DashboardIcon, MapIcon, TreeIcon } from "../components/icons";
import { useAsync } from "../hooks/useAsync";
import { useCladeLabel } from "../hooks/useSiteConfig";
import { cladePath, isUnit } from "../lib/clade";
import { fmt, fmtCompact, fmtPct, fmtQuality } from "../lib/format";
import { NoBreakdown } from "./BreakdownPage";
import { useClade } from "./CladeLayout";

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

/** The Gaps view of one group: the biggest under-sequenced groups inside it (most
 *  species with no data for a chosen resource) at a chosen rank. Rank, resource
 *  and view live in the URL, so a view is shareable. Reuses the breakdown
 *  machinery server-side (one ltree query). */
export default function GapsPage() {
  const clade = useClade();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const root = clade.taxid;
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

  const cladeLabel = useCladeLabel();
  const metrics = useAsync(getMetricsConfig, []);
  const quality = useAsync(getQualityConfig, []);
  const unit = isUnit(clade);
  const gaps = useAsync(
    () => (unit ? Promise.resolve(null) : getGaps({ root, rank, resource, limit: 25 })),
    [root, rank, resource, unit],
  );

  const resourceLabel = metrics.data?.find((m) => m.key === resource)?.card_title ?? "data";
  const resourceLower = resourceLabel.toLowerCase();
  // The surfaced quality figures (best BUSCO, median coding genes) shown next to
  // each gap: the quality of the data that *does* exist.
  const headlineQ = (quality.data ?? []).filter((q) => q.headline);
  const items = gaps.data?.items ?? [];
  const rootName = cladeLabel(root) ?? clade.name;
  const maxGap = items.length ? items[0].gap : 1; // items are sorted gap-desc
  // Looking inside a group makes it the current one, one rank finer, keeping the
  // resource and the list/scatter choice.
  const lookInside = (taxid: number) => {
    const next = new URLSearchParams(params);
    next.set("rank", FINER[rank]);
    navigate(`${cladePath(taxid, "gaps")}?${next}`);
  };

  if (unit) return <NoBreakdown />;
  return (
    <section className="gaps">
      <header className="gaps__head">
        <h1 className="gaps__title">Where are the gaps in {rootName}?</h1>
        <p className="gaps__lede">
          The biggest groups with the least genomic data. Each is ranked by the number of species
          that still have no {resourceLower}, so a huge, barely-sequenced group rises to the top.
        </p>
      </header>

      <div className="gaps__controls">
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
              {fmt(gaps.data!.total_matches)} in all.
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
                  onLookInside={() => lookInside(it.taxid)}
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
  const label = useCladeLabel()(item.taxid) ?? item.name;
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
          <Link to={cladePath(item.taxid)} className="gaps-row__name">
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
              <span className="gaps-row__qstat gaps-row__qstat--none">No genomes yet</span>
            )}
          </div>
        )}
        <div className="gaps-row__meta">
          <span className="gaps-row__stat">
            {fmt(item.n_rows)} species · {fmtPct(item.percent)}% covered
          </span>
          <span className="gaps-row__links">
            <Link to={cladePath(item.taxid)} className="gaps-row__link">
              <DashboardIcon size={13} /> Summary
            </Link>
            <Link to={cladePath(item.taxid, "map")} className="gaps-row__link">
              <MapIcon size={13} /> Data map
            </Link>
            <Link to={cladePath(item.taxid, "tree")} className="gaps-row__link">
              <TreeIcon size={13} /> Tree
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
