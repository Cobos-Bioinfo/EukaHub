import type { CSSProperties } from "react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { exportTsvUrl, getBreakdown, type BreakdownParams } from "../api/queries";
import type {
  FilterLogic,
  MetricConfig,
  MetricFilter,
  ResourceSummary,
  SortColumn,
  TargetRank,
} from "../api/types";
import { useAsync } from "../hooks/useAsync";
import {
  TARGET_RANKS,
  defaultRank,
  displayedRowsTsv,
  downloadText,
  sortOptions,
} from "../lib/breakdown";
import { fmt, fmtPct } from "../lib/format";
import DivergentBarChart from "./DivergentBarChart";

const LIMITS = [10, 25, 50, 100, 250];
type View = "table" | "chart";

/** The breakdown (Q2) view for one root: controls + a comparison table of its
 *  descendants at a chosen rank, with coverage meters and TSV downloads.
 *  Mount with `key={taxid}` so a new root resets the controls. */
export default function BreakdownSection({
  taxid,
  rootName,
  rootRank,
  metrics,
}: {
  taxid: number;
  rootName: string;
  rootRank: string;
  metrics: MetricConfig[];
}) {
  const [rank, setRank] = useState<TargetRank>(() => defaultRank(rootRank));
  const [sort, setSort] = useState<SortColumn>("n_rows");
  const [filters, setFilters] = useState<MetricFilter[]>([]);
  const [logic, setLogic] = useState<FilterLogic>("AND");
  const [excludeEmpty, setExcludeEmpty] = useState(true);
  const [limit, setLimit] = useState(25);
  const [view, setView] = useState<View>("table");

  const params: BreakdownParams = {
    rank,
    sort,
    filter: filters.length ? filters : undefined,
    logic,
    exclude_empty: excludeEmpty,
    limit,
  };

  const breakdown = useAsync(
    () => getBreakdown(taxid, params),
    [taxid, rank, sort, filters.join(","), logic, excludeEmpty, limit],
  );

  const toggleFilter = (key: MetricFilter) =>
    setFilters((cur) =>
      cur.includes(key) ? cur.filter((k) => k !== key) : [...cur, key],
    );

  const data = breakdown.data;
  const activeKey = sort === "n_rows" ? "n_rows" : sort.slice(2); // "c_ass" -> "ass"

  return (
    <section className="bd">
      <header className="bd__head">
        <h2 className="bd__title">Breakdown</h2>
        <p className="bd__sub">
          How <strong>{rootName}</strong> is distributed at a lower rank.
        </p>
      </header>

      <div className="bd__controls">
        <label className="control">
          <span className="control__label">Rank</span>
          <select
            className="control__select"
            value={rank}
            onChange={(e) => setRank(e.target.value as TargetRank)}
          >
            {TARGET_RANKS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>

        <label className="control">
          <span className="control__label">Sort by</span>
          <select
            className="control__select"
            value={sort}
            onChange={(e) => setSort(e.target.value as SortColumn)}
          >
            {sortOptions(metrics).map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>

        <label className="control">
          <span className="control__label">Show</span>
          <select
            className="control__select"
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
          >
            {LIMITS.map((n) => (
              <option key={n} value={n}>
                Top {n}
              </option>
            ))}
          </select>
        </label>

        <fieldset className="control control--filters">
          <span className="control__label">Has data for</span>
          <div className="bd__filters">
            {metrics.map((m) => (
              <label key={m.key} className="chip">
                <input
                  type="checkbox"
                  checked={filters.includes(m.key as MetricFilter)}
                  onChange={() => toggleFilter(m.key as MetricFilter)}
                />
                <span className="chip__dot" style={{ background: m.color }} aria-hidden="true" />
                {m.filter_label}
              </label>
            ))}
            <div
              className="bd__logic"
              role="radiogroup"
              aria-label="Combine filters with"
              data-disabled={filters.length < 2}
            >
              {(["AND", "OR"] as FilterLogic[]).map((op) => (
                <button
                  key={op}
                  type="button"
                  role="radio"
                  aria-checked={logic === op}
                  className={`seg${logic === op ? " seg--on" : ""}`}
                  onClick={() => setLogic(op)}
                >
                  {op}
                </button>
              ))}
            </div>
          </div>
        </fieldset>

        <label className="chip chip--toggle">
          <input
            type="checkbox"
            checked={excludeEmpty}
            onChange={(e) => setExcludeEmpty(e.target.checked)}
          />
          Hide taxa with no data
        </label>
      </div>

      {breakdown.error ? (
        <p className="notice notice--error">{breakdown.error}</p>
      ) : !data ? (
        <p className="notice">Loading breakdown…</p>
      ) : data.items.length === 0 ? (
        <p className="notice">No {rank}-rank taxa under {rootName} match these filters.</p>
      ) : (
        <>
          <div className="bd__meta">
            <div className="bd__meta-left">
              <div className="bd__view" role="tablist" aria-label="Result view">
                {(["table", "chart"] as View[]).map((v) => (
                  <button
                    key={v}
                    type="button"
                    role="tab"
                    aria-selected={view === v}
                    className={`seg${view === v ? " seg--on" : ""}`}
                    onClick={() => setView(v)}
                  >
                    {v === "table" ? "Table" : "Chart"}
                  </button>
                ))}
              </div>
              <span>
                Showing <strong>{fmt(data.returned)}</strong> of{" "}
                <strong>{fmt(data.total_matches)}</strong> {rank}-rank taxa
              </span>
            </div>
            <div className="bd__downloads">
              <button
                type="button"
                className="dl"
                onClick={() =>
                  downloadText(
                    `${rootName.replace(/\s+/g, "_")}_${rank}_shown.tsv`,
                    displayedRowsTsv(data, metrics),
                  )
                }
              >
                ↓ Shown rows
              </button>
              <a className="dl" href={exportTsvUrl(taxid, params)}>
                ↓ Full breakdown
              </a>
            </div>
          </div>

          {view === "chart" ? (
            <div className="chart-wrap">
              <DivergentBarChart items={data.items} metrics={metrics} />
            </div>
          ) : (
            <div className="bd__table-wrap">
            <table className="bd-table">
              <thead>
                <tr>
                  <th scope="col">Taxon</th>
                  <th
                    scope="col"
                    className={`bd-num${activeKey === "n_rows" ? " bd-th--active" : ""}`}
                  >
                    Species
                  </th>
                  {metrics.map((m) => (
                    <th
                      key={m.key}
                      scope="col"
                      className={`bd-metric${activeKey === m.key ? " bd-th--active" : ""}`}
                    >
                      <span className="bd-metric__dot" style={{ background: m.color }} aria-hidden="true" />
                      {m.card_title}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.taxid}>
                    <td className="bd-name">
                      <Link to={`/clade/${item.taxid}`}>{item.name}</Link>
                    </td>
                    <td className="bd-num">{fmt(item.n_rows)}</td>
                    {metrics.map((m) => (
                      <td key={m.key}>
                        <CoverageCell
                          color={m.color}
                          resource={item.resources[m.key]}
                          nRows={item.n_rows}
                        />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}

/** One metric cell: a coverage meter (share of the clade's species with the
 *  resource) plus the covered count and percent; the summed total is on hover. */
function CoverageCell({
  color,
  resource,
  nRows,
}: {
  color: string;
  resource: ResourceSummary;
  nRows: number;
}) {
  const { covered, total, percent } = resource;
  return (
    <div
      className="cov"
      style={{ "--metric-color": color } as CSSProperties}
      title={`${fmt(covered)} of ${fmt(nRows)} species · ${fmt(total)} total`}
    >
      <div className="cov__nums">
        <span className="cov__cov">{fmt(covered)}</span>
        <span className="cov__pct">{fmtPct(percent)}%</span>
      </div>
      <div className="cov__meter" aria-hidden="true">
        <div className="cov__fill" style={{ width: `${Math.min(percent, 100)}%` }} />
      </div>
    </div>
  );
}
