import { useState } from "react";
import { Link } from "react-router-dom";

import type { CladeSummary, MetricConfig } from "../api/types";
import { fmt, fmtPct } from "../lib/format";

// The four corners of the mirrored bar, resolved from the metric config's
// side/overlay flags (ported from Euka-Survey's divergent bar): the lighter
// base metric on each side with its darker subset metric overlaid on top.
interface Roles {
  leftBase: MetricConfig;
  leftOverlay: MetricConfig;
  rightBase: MetricConfig;
  rightOverlay: MetricConfig;
}

function chartRoles(metrics: MetricConfig[]): Roles | null {
  const find = (side: string, overlay: boolean) =>
    metrics.find((m) => m.side === side && m.overlay === overlay);
  const leftBase = find("left", false);
  const leftOverlay = find("left", true);
  const rightBase = find("right", false);
  const rightOverlay = find("right", true);
  if (!leftBase || !leftOverlay || !rightBase || !rightOverlay) return null;
  return { leftBase, leftOverlay, rightBase, rightOverlay };
}

interface HoverState {
  item: CladeSummary;
  x: number;
  y: number;
}

/** Divergent (back-to-back) coverage chart: one mirrored bar per taxon,
 *  encoding the % of each clade's species with each resource. Left half =
 *  assemblies + annotations (blue), right half = RNA-Seq + long-read (green);
 *  the darker metric of each pair is overlaid on its lighter base. Bars sit on
 *  a grey track with an inset edge so the pale base hues read (the relief the
 *  palette validator flags as required on a near-white surface). */
export default function DivergentBarChart({
  items,
  metrics,
}: {
  items: CladeSummary[];
  metrics: MetricConfig[];
}) {
  const [hover, setHover] = useState<HoverState | null>(null);
  const roles = chartRoles(metrics);
  if (!roles) return null;

  return (
    <div className="chart">
      {/* Axis header: coverage % ticks aligned over the bar track. */}
      <div className="chart__row chart__row--axis" aria-hidden="true">
        <span className="chart__name" />
        <div className="chart__ticks">
          {["100%", "50", "0", "50", "100%"].map((t, i) => (
            <span key={i}>{t}</span>
          ))}
        </div>
        <span className="chart__count">Species</span>
      </div>

      {items.map((item) => (
        <div
          key={item.taxid}
          className="chart__row"
          onMouseMove={(e) => setHover({ item, x: e.clientX, y: e.clientY })}
          onMouseLeave={() => setHover((h) => (h?.item.taxid === item.taxid ? null : h))}
        >
          <Link className="chart__name" to={`/clade/${item.taxid}`} title={item.name}>
            {item.name}
          </Link>

          <div className="chart__track">
            <span className="chart__axis" aria-hidden="true" />
            <Bar metric={roles.leftBase} item={item} side="l" />
            <Bar metric={roles.leftOverlay} item={item} side="l" overlay />
            <Bar metric={roles.rightBase} item={item} side="r" />
            <Bar metric={roles.rightOverlay} item={item} side="r" overlay />
          </div>

          <span className="chart__count">{fmt(item.n_rows)}</span>
        </div>
      ))}

      <Legend metrics={metrics} />

      {hover && (
        <div
          className="chart-tip"
          style={{ left: hover.x + 14, top: hover.y + 14 }}
          role="tooltip"
        >
          <div className="chart-tip__name">{hover.item.name}</div>
          <div className="chart-tip__sub">{fmt(hover.item.n_rows)} species</div>
          {metrics.map((m) => {
            const r = hover.item.resources[m.key];
            return (
              <div key={m.key} className="chart-tip__row">
                <span className="chart-tip__dot" style={{ background: m.color }} />
                <span className="chart-tip__label">{m.card_title}</span>
                <span className="chart-tip__val">
                  {fmtPct(r.percent)}% · {fmt(r.covered)} sp · {fmt(r.total)}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/** One bar segment: width = coverage %/2 (each side spans half the track). */
function Bar({
  metric,
  item,
  side,
  overlay = false,
}: {
  metric: MetricConfig;
  item: CladeSummary;
  side: "l" | "r";
  overlay?: boolean;
}) {
  const pct = item.resources[metric.key].percent;
  if (pct <= 0) return null;
  const cls = `dbar dbar--${side}${overlay ? " dbar--overlay" : ""}`;
  return (
    <span
      className={cls}
      style={{ width: `${Math.min(pct, 100) / 2}%`, background: metric.color }}
    />
  );
}

function Legend({ metrics }: { metrics: MetricConfig[] }) {
  return (
    <div className="chart-legend">
      <span className="chart-legend__axis">assemblies / annotations ←</span>
      {metrics.map((m) => (
        <span key={m.key} className="chart-legend__item">
          <span className="chart-legend__dot" style={{ background: m.color }} />
          {m.legend_label}
        </span>
      ))}
      <span className="chart-legend__axis">→ RNA-Seq</span>
    </div>
  );
}
