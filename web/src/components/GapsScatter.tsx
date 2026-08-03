import { useState } from "react";

import type { GapItem, QualityStatConfig } from "../api/types";
import { cladeLabel } from "../lib/clades";
import { fmt, fmtCompact, fmtPct, fmtQuality } from "../lib/format";

// A single-series scatter of the gap clades: x = species (log), y = coverage %,
// bubble size = species missing data (the gap). One hue (the shared --gap amber,
// already validated as the leaderboard's gap bar), so no legend is needed; the
// List view is the accessible table fallback. Layout is a fixed viewBox scaled
// to the container width.
const VBW = 820;
const VBH = 460;
const M = { top: 20, right: 22, bottom: 48, left: 60 };
const PW = VBW - M.left - M.right;
const PH = VBH - M.top - M.bottom;
const RMIN = 5;
const RMAX = 20;

/** Round up to a "nice" 1/2/5 x 10^n ceiling, for a clean top y-tick. */
function niceCeil(x: number): number {
  if (x <= 0) return 1;
  const exp = Math.floor(Math.log10(x));
  const base = 10 ** exp;
  const f = x / base;
  const nf = f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10;
  return nf * base;
}

/** The scatter secondary view for /gaps. Shows that coverage does not rise with
 *  clade size: the biggest groups sit low and carry the largest bubbles. Reuses
 *  the same loaded items as the leaderboard (no extra fetch). */
export default function GapsScatter({
  items,
  resourceLower,
  qstats,
}: {
  items: GapItem[];
  resourceLower: string;
  qstats: QualityStatConfig[];
}) {
  const [hover, setHover] = useState<number | null>(null);

  // x = species, log10, with ~12% of a decade of padding each side so edge
  // points sit off the frame. Ticks are the whole powers of 10 inside the
  // padded range (clean 10K / 100K labels) rather than the enclosing decades,
  // so a cluster that stops mid-decade doesn't leave an empty decade of space.
  const xs = items.map((it) => Math.max(it.n_rows, 1));
  const xLo = Math.log10(Math.min(...xs)) - 0.12;
  const xHi = Math.log10(Math.max(...xs)) + 0.12;
  const xSpan = xHi - xLo || 1;
  const xScale = (v: number) => M.left + ((Math.log10(Math.max(v, 1)) - xLo) / xSpan) * PW;
  const xTicks: number[] = [];
  for (let e = Math.ceil(xLo); e <= Math.floor(xHi); e++) xTicks.push(10 ** e);
  if (xTicks.length < 2) xTicks.push(Math.min(...xs), Math.max(...xs)); // degenerate span

  // y = coverage %, auto-scaled (gaps are low-coverage by design), floored at 5%
  // so a cluster of near-zero points still gets vertical room to separate.
  const yMax = Math.min(100, Math.max(5, niceCeil(Math.max(...items.map((it) => it.percent)))));
  const yScale = (v: number) => M.top + PH - (Math.min(v, yMax) / yMax) * PH;
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * yMax);

  // Bubble area proportional to the gap; sqrt keeps big clades from dominating.
  const maxGap = Math.max(...items.map((it) => it.gap), 1);
  const rScale = (g: number) => Math.max(RMIN, Math.min(RMAX, Math.sqrt(g / maxGap) * RMAX));

  // Paint big bubbles first so the small ones stay hoverable on top.
  const order = items.map((_, i) => i).sort((a, b) => items[b].gap - items[a].gap);

  const active = hover === null ? null : items[hover];
  const headline = qstats.filter((q) => q.headline);

  const tip = active
    ? {
        left: Math.min(88, Math.max(12, (xScale(active.n_rows) / VBW) * 100)),
        top: (yScale(active.percent) / VBH) * 100,
        below: yScale(active.percent) < M.top + PH * 0.4,
      }
    : null;

  return (
    <div className="gscatter">
      <svg
        className="gscatter__svg"
        viewBox={`0 0 ${VBW} ${VBH}`}
        role="img"
        aria-label={
          `Scatter of ${items.length} groups: species count versus the percent with ` +
          `${resourceLower}. Bubble size is the number of species missing data. The List ` +
          `view has the same groups as a ranked list.`
        }
      >
        {yTicks.map((t) => {
          const y = yScale(t);
          return (
            <g key={`y${t}`}>
              <line x1={M.left} y1={y} x2={M.left + PW} y2={y} className="gscatter__grid" />
              <text
                x={M.left - 8}
                y={y}
                className="gscatter__ylab"
                dominantBaseline="middle"
                textAnchor="end"
              >
                {fmtPct(t)}%
              </text>
            </g>
          );
        })}
        {xTicks.map((t) => {
          const x = xScale(t);
          return (
            <g key={`x${t}`}>
              <line
                x1={x}
                y1={M.top}
                x2={x}
                y2={M.top + PH}
                className="gscatter__grid gscatter__grid--v"
              />
              <text x={x} y={M.top + PH + 18} className="gscatter__xlab" textAnchor="middle">
                {fmtCompact(t)}
              </text>
            </g>
          );
        })}

        <text x={M.left + PW / 2} y={VBH - 6} className="gscatter__axis" textAnchor="middle">
          Species in the group (log scale)
        </text>
        <text
          transform={`translate(15 ${M.top + PH / 2}) rotate(-90)`}
          className="gscatter__axis"
          textAnchor="middle"
        >
          % with {resourceLower}
        </text>

        {order.map((i) => {
          const it = items[i];
          const on = hover === i;
          return (
            <circle
              key={it.taxid}
              cx={xScale(it.n_rows)}
              cy={yScale(it.percent)}
              r={rScale(it.gap)}
              className={`gscatter__dot${on ? " gscatter__dot--on" : ""}`}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover((h) => (h === i ? null : h))}
            >
              <title>
                {`${cladeLabel(it.taxid) ?? it.name}: ${fmt(it.gap)} of ${fmt(it.n_rows)} species missing ${resourceLower}`}
              </title>
            </circle>
          );
        })}
      </svg>

      {active && tip && (
        <div
          className={`gscatter__tip${tip.below ? " gscatter__tip--below" : ""}`}
          style={{ left: `${tip.left}%`, top: `${tip.top}%` }}
        >
          <div className="gscatter__tip-name">{cladeLabel(active.taxid) ?? active.name}</div>
          <div className="gscatter__tip-row">
            <strong>{fmtCompact(active.gap)}</strong> of {fmt(active.n_rows)} species missing{" "}
            {resourceLower}
          </div>
          <div className="gscatter__tip-row gscatter__tip-muted">
            {fmtPct(active.percent)}% covered
          </div>
          {headline.length > 0 && (
            <div className="gscatter__tip-q">
              {headline.map((q) => {
                const v = active.stats.find((s) => s.key === q.key)?.value ?? null;
                return (
                  <span key={q.key} className="gscatter__tip-qstat">
                    {q.card_title}: <strong>{fmtQuality(v, q.fmt)}</strong>
                  </span>
                );
              })}
            </div>
          )}
        </div>
      )}

      <p className="gscatter__note">
        Each bubble is a group: position shows its size and coverage, bubble size shows the number of
        species still missing {resourceLower}. Hover for details, or switch to the List view.
      </p>
    </div>
  );
}
