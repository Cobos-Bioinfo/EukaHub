import { hierarchy, tree as d3tree } from "d3-hierarchy";
import { linkRadial, pointRadial } from "d3-shape";
import { useEffect, useMemo, useRef, useState } from "react";

import type { MetricConfig, TaxonNode } from "../api/types";
import type { Tree, TreeNode } from "../hooks/useTree";
import { fmt, fmtPct } from "../lib/format";

// --- Encodings --------------------------------------------------------------
// Node COLOR = a sequential single-hue (blue) ramp of assembly coverage % — the
// "is there a genome?" magnitude (dataviz skill: magnitude → one hue light→dark;
// the tooltip carries all four metrics). Grey = no species tracked in the clade.
const COLOR_KEY = "ass"; // metric coloured by (assemblies)
const NO_DATA = "#cbd5e1";
const RAMP = ["#e7f0fc", "#bcd4f6", "#7fb0ee", "#4287e0", "#1d4ed8"] as const;

function coverageColor(node: TaxonNode): string {
  if (node.n_rows <= 0) return NO_DATA;
  const pct = node.resources[COLOR_KEY]?.percent ?? 0;
  const i = pct <= 0 ? 0 : pct < 25 ? 1 : pct < 50 ? 2 : pct < 75 ? 3 : 4;
  return RAMP[i];
}

// Node SIZE = √(species count) so area tracks species, clamped and scaled to the
// largest node in view so one 1.3M-species clade doesn't dwarf the rest.
const R_MIN = 3.5;
const R_MAX = 15;
function nodeRadius(n: number, maxN: number): number {
  if (n <= 0 || maxN <= 0) return R_MIN;
  return R_MIN + (R_MAX - R_MIN) * Math.min(1, Math.sqrt(n) / Math.sqrt(maxN));
}

// --- Layout geometry --------------------------------------------------------
const VIEW = 1000; // logical viewBox size; SVG scales to its container via CSS
const CENTER = VIEW / 2;
const RING = 120; // radius per depth level
const MIN_K = 0.15;
const MAX_K = 4;

// Datum for the d3 hierarchy: real taxon nodes plus synthetic "load more" leaves.
type Datum =
  | { kind: "node"; key: string; taxid: number; tn: TreeNode; children?: Datum[] }
  | { kind: "more"; key: string; parentId: number; remaining: number };

function buildVisible(
  nodes: Record<number, TreeNode>,
  rootId: number,
): Datum | null {
  const build = (id: number): Datum => {
    const tn = nodes[id];
    let children: Datum[] | undefined;
    if (tn.expanded) {
      children = tn.childIds.filter((c) => nodes[c]).map(build);
      if (tn.childIds.length < tn.totalChildren) {
        children.push({
          kind: "more",
          key: `more-${id}`,
          parentId: id,
          remaining: tn.totalChildren - tn.childIds.length,
        });
      }
    }
    return { kind: "node", key: `node-${id}`, taxid: id, tn, children };
  };
  return nodes[rootId] ? build(rootId) : null;
}

const linkPath = linkRadial<unknown, { x: number; y: number }>()
  .angle((d) => d.x)
  .radius((d) => d.y);

interface HoverState {
  node: TaxonNode;
  x: number;
  y: number;
}

/**
 * The interactive radial "Tree of Life". Renders the currently loaded/expanded
 * hierarchy from `tree` (a `useTree` instance) as a radial dendrogram: curved
 * links, nodes sized by species count and coloured by assembly coverage, radial
 * labels, a hover tooltip, click-to-expand, and pan/zoom. Clicking a node's
 * label opens its dashboard via `onOpen`.
 */
export default function RadialTree({
  tree,
  metrics,
  onOpen,
}: {
  tree: Tree;
  metrics: MetricConfig[];
  onOpen: (taxid: number) => void;
}) {
  const { nodes, rootId } = tree;
  const [hover, setHover] = useState<HoverState | null>(null);
  const [view, setView] = useState({ k: 1, tx: 0, ty: 0 });
  const svgRef = useRef<SVGSVGElement>(null);
  const drag = useRef<{ x: number; y: number; moved: boolean } | null>(null);

  // Reset pan/zoom whenever the tree root changes.
  useEffect(() => setView({ k: 1, tx: 0, ty: 0 }), [rootId]);

  const laid = useMemo(() => {
    if (rootId == null) return null;
    const datum = buildVisible(nodes, rootId);
    if (!datum) return null;
    const hier = hierarchy<Datum>(datum, (d) => (d.kind === "node" ? d.children : undefined));
    const totalR = Math.max(1, hier.height) * RING;
    // The layout returns the positioned hierarchy (nodes gain x = angle, y = radius).
    const root = d3tree<Datum>()
      .size([2 * Math.PI, totalR])
      .separation((a, b) => (a.parent === b.parent ? 1 : 2) / Math.max(1, a.depth))(hier);
    // Largest species count in view drives the size scale.
    let maxN = 1;
    root.each((d) => {
      if (d.data.kind === "node") maxN = Math.max(maxN, d.data.tn.node.n_rows);
    });
    return { root, maxN };
  }, [nodes, rootId]);

  if (rootId == null || !laid) {
    return <p className="notice">Loading tree…</p>;
  }
  const { root, maxN } = laid;

  // Convert a pixel delta on the (square, meet-scaled) SVG to logical units.
  const logicalPerPx = () => VIEW / (svgRef.current?.clientWidth || VIEW);

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
    setView((v) => ({ ...v, k: Math.min(MAX_K, Math.max(MIN_K, v.k * factor)) }));
  };
  const onPointerDown = (e: React.PointerEvent) => {
    drag.current = { x: e.clientX, y: e.clientY, moved: false };
    (e.target as Element).setPointerCapture?.(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag.current) return;
    const dx = e.clientX - drag.current.x;
    const dy = e.clientY - drag.current.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) drag.current.moved = true;
    drag.current.x = e.clientX;
    drag.current.y = e.clientY;
    const s = logicalPerPx();
    setView((v) => ({ ...v, tx: v.tx + dx * s, ty: v.ty + dy * s }));
  };
  const onPointerUp = () => {
    drag.current = null;
  };

  return (
    <div className="tree">
      <svg
        ref={svgRef}
        className="tree__svg"
        viewBox={`0 0 ${VIEW} ${VIEW}`}
        role="img"
        aria-label="Interactive radial tree of life; use the outline below for a keyboard-accessible view."
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
      >
        <g
          transform={`translate(${CENTER + view.tx} ${CENTER + view.ty}) scale(${view.k})`}
        >
          {/* Links */}
          <g className="tree__links" fill="none">
            {root.links().map((l) => (
              <path
                key={`${(l.source.data as Datum).key}-${(l.target.data as Datum).key}`}
                d={linkPath({ source: l.source, target: l.target }) ?? undefined}
              />
            ))}
          </g>

          {/* Nodes */}
          {root.descendants().map((d) => {
            const [x, y] = pointRadial(d.x, d.y);
            const data = d.data; // const → discriminant narrowing survives into the closures below
            if (data.kind === "more") {
              return (
                <MoreNode
                  key={data.key}
                  x={x}
                  y={y}
                  remaining={data.remaining}
                  onClick={() => !drag.current?.moved && tree.loadMore(data.parentId)}
                />
              );
            }
            return (
              <TreeNodeMark
                key={data.key}
                x={x}
                y={y}
                angle={d.x}
                isRoot={d.depth === 0}
                r={nodeRadius(data.tn.node.n_rows, maxN)}
                treeNode={data.tn}
                onToggle={() => !drag.current?.moved && tree.toggle(data.taxid)}
                onOpen={() => onOpen(data.taxid)}
                onHover={(x2, y2) => setHover({ node: data.tn.node, x: x2, y: y2 })}
                onLeave={() => setHover(null)}
              />
            );
          })}
        </g>
      </svg>

      <Legend metrics={metrics} />

      {hover && (
        <div
          className="chart-tip"
          style={{ left: hover.x + 14, top: hover.y + 14 }}
          role="tooltip"
        >
          <div className="chart-tip__name">{hover.node.name}</div>
          <div className="chart-tip__sub">
            {hover.node.rank} · {fmt(hover.node.n_rows)} species
          </div>
          {metrics.map((m) => {
            const r = hover.node.resources[m.key];
            return (
              <div key={m.key} className="chart-tip__row">
                <span className="chart-tip__dot" style={{ background: m.color }} />
                <span className="chart-tip__label">{m.card_title}</span>
                <span className="chart-tip__val">
                  {fmtPct(r.percent)}% · {fmt(r.covered)} sp
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/** One taxon node: a circle (expand/collapse) plus a radial label (opens the
 *  dashboard). The label is rotated to its branch angle and flipped on the left
 *  half so it always reads left-to-right. */
function TreeNodeMark({
  x,
  y,
  angle,
  isRoot,
  r,
  treeNode,
  onToggle,
  onOpen,
  onHover,
  onLeave,
}: {
  x: number;
  y: number;
  angle: number;
  isRoot: boolean;
  r: number;
  treeNode: TreeNode;
  onToggle: () => void;
  onOpen: () => void;
  onHover: (x: number, y: number) => void;
  onLeave: () => void;
}) {
  const { node, expanded, loading } = treeNode;
  const onLeft = angle >= Math.PI;
  const labelDeg = (angle * 180) / Math.PI - 90;
  const canExpand = node.has_children;
  const name = node.name.length > 22 ? node.name.slice(0, 21) + "…" : node.name;

  return (
    <g
      className="tree__node"
      onMouseMove={(e) => onHover(e.clientX, e.clientY)}
      onMouseLeave={onLeave}
    >
      <circle
        cx={x}
        cy={y}
        r={r}
        fill={coverageColor(node)}
        className={
          "tree__dot" +
          (canExpand ? " tree__dot--expandable" : "") +
          (expanded ? " tree__dot--expanded" : "") +
          (loading ? " tree__dot--loading" : "")
        }
        onClick={canExpand ? onToggle : undefined}
      >
        <title>
          {node.name} — {fmt(node.n_rows)} species
          {canExpand ? (expanded ? " (click to collapse)" : " (click to expand)") : ""}
        </title>
      </circle>

      {isRoot ? (
        <text className="tree__label tree__label--root" x={x} y={y - r - 6} onClick={onOpen}>
          {name}
        </text>
      ) : (
        <text
          className="tree__label"
          transform={`rotate(${labelDeg} ${x} ${y}) translate(${onLeft ? -(r + 5) : r + 5} 0) ${onLeft ? "rotate(180)" : ""}`}
          x={x}
          y={y}
          dy="0.32em"
          textAnchor={onLeft ? "end" : "start"}
          onClick={onOpen}
        >
          {name}
        </text>
      )}
    </g>
  );
}

/** Synthetic "load more" leaf shown when a node has more children than loaded. */
function MoreNode({
  x,
  y,
  remaining,
  onClick,
}: {
  x: number;
  y: number;
  remaining: number;
  onClick: () => void;
}) {
  return (
    <g className="tree__more" onClick={onClick}>
      <circle cx={x} cy={y} r={7} className="tree__more-dot" />
      <text x={x} y={y} dy="0.32em" textAnchor="middle" className="tree__more-label">
        +{remaining > 99 ? "99+" : remaining}
      </text>
      <title>Load {remaining} more</title>
    </g>
  );
}

function Legend({ metrics }: { metrics: MetricConfig[] }) {
  const colorMetric = metrics.find((m) => m.key === COLOR_KEY);
  return (
    <div className="tree-legend">
      <span className="tree-legend__title">
        Node colour · {colorMetric?.card_title ?? "assembly"} coverage
      </span>
      <span className="tree-legend__ramp">
        <span className="tree-legend__cap">0%</span>
        {RAMP.map((c) => (
          <span key={c} className="tree-legend__step" style={{ background: c }} />
        ))}
        <span className="tree-legend__cap">100%</span>
      </span>
      <span className="tree-legend__item">
        <span className="tree-legend__step" style={{ background: NO_DATA }} /> no species
      </span>
      <span className="tree-legend__hint">
        size ∝ species · click a node to expand · click a name to open it
      </span>
    </div>
  );
}
