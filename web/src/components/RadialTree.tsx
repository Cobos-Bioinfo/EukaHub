import { hierarchy, tree as d3tree } from "d3-hierarchy";
import { linkRadial } from "d3-shape";
import { useEffect, useMemo, useRef, useState } from "react";

import type { MetricConfig, TaxonNode } from "../api/types";
import type { Tree, TreeNode } from "../hooks/useTree";
import { fmt, fmtPct } from "../lib/format";
import { useTheme } from "../lib/theme";

// --- Encodings --------------------------------------------------------------
// Node COLOUR = a sequential ramp in the *selected resource's own hue* (dataviz
// skill: magnitude → one hue light→dark), so "Colour by" adopts each category's
// identity colour — assemblies light-blue, annotations dark-blue, RNA-Seq green,
// long-read dark-green — matching the cards/chart. The details panel carries all
// four; grey = no species tracked in the clade.
//
// Coverage is heavily right-skewed (most clades sit at 0–10%, a few reach 100%),
// so a linear scale would paint almost everything the palest tint. We map with a
// gamma curve (pct^0.35) that spreads the low end, then interpolate a per-metric
// ramp continuously. The ramp is a *selected* dark variant, not a flip (dataviz
// skill): on the light canvas it runs faint→colour→dark (more ink = more data);
// on the dark canvas it runs dim→colour→bright (more light = more data), so high
// coverage stays the high-contrast end against either surface.
type RGB = [number, number, number];
const NO_DATA_LIGHT = "#cbd5e1"; // pale slate, recessive on white
const NO_DATA_DARK = "#3a4150"; // dim slate, recessive on the dark canvas
const WHITE: RGB = [255, 255, 255];
const BLACK: RGB = [0, 0, 0];
const DARK_SURF: RGB = [15, 18, 22]; // matches --surface (dark)
const hexRgb = (h: string): RGB => [
  parseInt(h.slice(1, 3), 16),
  parseInt(h.slice(3, 5), 16),
  parseInt(h.slice(5, 7), 16),
];
const rgbStr = (c: RGB) => `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
const mix = (c: RGB, t: RGB, f: number): RGB =>
  [0, 1, 2].map((i) => Math.round(c[i] + (t[i] - c[i]) * f)) as RGB;

/** Build a metric's sequential ramp from its identity hue, anchored for the theme. */
function buildRamp(hex: string, dark: boolean): RGB[] {
  const c = hexRgb(hex);
  return dark
    ? [mix(c, DARK_SURF, 0.4), c, mix(c, WHITE, 0.45)]
    : [mix(c, WHITE, 0.82), c, mix(c, BLACK, 0.28)];
}

function coverageColor(node: TaxonNode, key: string, ramp: RGB[], noData: string): string {
  if (node.n_rows <= 0) return noData;
  const pct = node.resources[key]?.percent ?? 0;
  if (pct <= 0) return rgbStr(ramp[0]);
  const t = Math.min(1, Math.pow(pct / 100, 0.35)); // gamma-spread the low end
  const x = t * (ramp.length - 1);
  const i = Math.min(ramp.length - 2, Math.floor(x));
  return rgbStr(mix(ramp[i], ramp[i + 1], x - i));
}

// Node SIZE = √(species count), clamped and scaled to the largest node in view.
const R_MIN = 7;
const R_MAX = 26;
function nodeRadius(n: number, maxN: number): number {
  if (n <= 0 || maxN <= 0) return R_MIN;
  return R_MIN + (R_MAX - R_MIN) * Math.min(1, Math.sqrt(n) / Math.sqrt(maxN));
}

const truncate = (s: string) => (s.length > 24 ? s.slice(0, 23) + "…" : s);

// --- Layout geometry --------------------------------------------------------
// The viewBox is measured from the container at runtime (see the ResizeObserver
// below) so it matches the on-screen pixel box exactly — the SVG neither
// down-scales nor letterboxes, and nodes/labels render at their intended px on
// any canvas size (near-fullscreen on the full-bleed tree page). VW/VH are only
// the pre-measurement fallback for the first paint.
const VW = 1100;
const VH = 760;
// Rings sit a fixed distance apart (RING) so expanding grows the tree outward at
// constant, readable spacing instead of cramming; a floor (fillR, derived from
// the smaller container dimension) keeps a shallow tree filling the view rather
// than shrinking to a dot. Deep trees spill past the edge — that's what pan/zoom
// is for. Using the *smaller* dimension leaves horizontal room for the radial
// labels (the 3/9-o'clock ones extend furthest) so they clip less.
const RING = 135;
const MIN_K = 0.2;
const MAX_K = 5;

type Datum =
  | { kind: "node"; key: string; taxid: number; tn: TreeNode; children?: Datum[] }
  | { kind: "more"; key: string; parentId: number; remaining: number };

function buildVisible(nodes: Record<number, TreeNode>, rootId: number): Datum | null {
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
 * The interactive radial "Tree of Life". Renders the loaded/expanded hierarchy
 * from `tree` (a `useTree` instance) as a radial dendrogram — curved links,
 * nodes sized by species count and coloured by a chosen resource's coverage,
 * radial labels, pan/zoom (+ buttons), a light hover tooltip, and a click-to-
 * select details panel from which the user opens a node's dashboard.
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
  const [selected, setSelected] = useState<number | null>(null);
  const [colorKey, setColorKey] = useState(metrics[0]?.key ?? "ass");
  const activeMetric = metrics.find((m) => m.key === colorKey);
  const dark = useTheme() === "dark";
  const noData = dark ? NO_DATA_DARK : NO_DATA_LIGHT;
  const ramp = useMemo(
    () => buildRamp(activeMetric?.color ?? "#1f6feb", dark),
    [activeMetric?.color, dark],
  );
  const svgRef = useRef<SVGSVGElement>(null);
  const drag = useRef<{ x: number; y: number; moved: boolean } | null>(null);
  // Live pixel size of the SVG box; the viewBox tracks it so the radial layout
  // fills whatever canvas the (near-fullscreen) container gives us.
  const [size, setSize] = useState({ w: VW, h: VH });
  const cx = size.w / 2;
  const cy = size.h / 2;

  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const cr = entries[0]?.contentRect;
      if (cr && cr.width > 0 && cr.height > 0) {
        setSize({ w: Math.round(cr.width), h: Math.round(cr.height) });
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Reset pan/zoom and selection whenever the tree root changes.
  useEffect(() => {
    setView({ k: 1, tx: 0, ty: 0 });
    setSelected(null);
  }, [rootId]);

  const laid = useMemo(() => {
    if (rootId == null) return null;
    const datum = buildVisible(nodes, rootId);
    if (!datum) return null;
    const hier = hierarchy<Datum>(datum, (d) => (d.kind === "node" ? d.children : undefined));
    const fillR = 0.34 * Math.min(size.w, size.h);
    const totalR = Math.max(fillR, hier.height * RING);
    const root = d3tree<Datum>()
      .size([2 * Math.PI, totalR])
      .separation((a, b) => (a.parent === b.parent ? 1 : 2) / Math.max(1, a.depth))(hier);
    let maxN = 1;
    root.each((d) => {
      if (d.data.kind === "node") maxN = Math.max(maxN, d.data.tn.node.n_rows);
    });
    return { root, maxN };
  }, [nodes, rootId, size.w, size.h]);

  if (rootId == null || !laid) return <p className="notice">Loading tree…</p>;
  const { root, maxN } = laid;

  const logicalPerPx = () => size.w / (svgRef.current?.clientWidth || size.w);
  const clampK = (k: number) => Math.min(MAX_K, Math.max(MIN_K, k));

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.05 : 1 / 1.05; // gentle
    setView((v) => ({ ...v, k: clampK(v.k * factor) }));
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

  const selectedNode = selected != null ? nodes[selected] : undefined;

  return (
    <div className="tree-wrap">
      <div className="tree-controls">
        <span className="tree-controls__label">Colour by</span>
        <div className="tree-controls__seg" role="group" aria-label="Colour nodes by resource">
          {metrics.map((m) => (
            <button
              key={m.key}
              type="button"
              className={"seg-btn" + (m.key === colorKey ? " seg-btn--on" : "")}
              onClick={() => setColorKey(m.key)}
            >
              <span className="seg-btn__dot" style={{ background: m.color }} />
              {m.card_title}
            </button>
          ))}
        </div>
      </div>

      <div className="tree">
        <svg
          ref={svgRef}
          className="tree__svg"
          viewBox={`0 0 ${size.w} ${size.h}`}
          role="img"
          aria-label="Interactive radial tree of life; use the outline below for a keyboard-accessible view."
          onWheel={onWheel}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerLeave={onPointerUp}
        >
          <g transform={`translate(${cx + view.tx} ${cy + view.ty}) scale(${view.k})`}>
            <g className="tree__links" fill="none">
              {root.links().map((l) => (
                <path
                  key={`${(l.source.data as Datum).key}-${(l.target.data as Datum).key}`}
                  d={linkPath({ source: l.source, target: l.target }) ?? undefined}
                />
              ))}
            </g>

            {root.descendants().map((d) => {
              const data = d.data;
              if (data.kind === "more") {
                return (
                  <MoreNode
                    key={data.key}
                    angle={d.x}
                    radius={d.y}
                    remaining={data.remaining}
                    onClick={() => !drag.current?.moved && tree.loadMore(data.parentId)}
                  />
                );
              }
              return (
                <TreeNodeMark
                  key={data.key}
                  angle={d.x}
                  radius={d.y}
                  isRoot={d.depth === 0}
                  selected={data.taxid === selected}
                  r={nodeRadius(data.tn.node.n_rows, maxN)}
                  treeNode={data.tn}
                  colorKey={colorKey}
                  ramp={ramp}
                  noData={noData}
                  onClick={() => {
                    if (drag.current?.moved) return;
                    setSelected(data.taxid);
                    tree.toggle(data.taxid);
                  }}
                  onHover={(x, y) => setHover({ node: data.tn.node, x, y })}
                  onLeave={() => setHover(null)}
                />
              );
            })}
          </g>
        </svg>

        <div className="tree-zoom">
          <button type="button" onClick={() => setView((v) => ({ ...v, k: clampK(v.k * 1.3) }))} aria-label="Zoom in">
            +
          </button>
          <button type="button" onClick={() => setView((v) => ({ ...v, k: clampK(v.k / 1.3) }))} aria-label="Zoom out">
            −
          </button>
          <button type="button" onClick={() => setView({ k: 1, tx: 0, ty: 0 })} aria-label="Reset view" title="Reset view">
            ⤢
          </button>
        </div>

        <Legend label={activeMetric?.card_title} ramp={ramp} noData={noData} />

        {selectedNode && (
          <DetailsPanel
            node={selectedNode.node}
            expanded={selectedNode.expanded}
            metrics={metrics}
            onOpen={() => onOpen(selectedNode.node.taxid)}
            onToggle={() => tree.toggle(selectedNode.node.taxid)}
            onClose={() => setSelected(null)}
          />
        )}

        {hover && (
          <div className="chart-tip" style={{ left: hover.x + 14, top: hover.y + 14 }} role="tooltip">
            <div className="chart-tip__name">{hover.node.name}</div>
            <div className="chart-tip__sub">
              {hover.node.rank} · {fmt(hover.node.n_rows)} species
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function TreeNodeMark({
  angle,
  radius,
  isRoot,
  selected,
  r,
  treeNode,
  colorKey,
  ramp,
  noData,
  onClick,
  onHover,
  onLeave,
}: {
  angle: number;
  radius: number;
  isRoot: boolean;
  selected: boolean;
  r: number;
  treeNode: TreeNode;
  colorKey: string;
  ramp: RGB[];
  noData: string;
  onClick: () => void;
  onHover: (x: number, y: number) => void;
  onLeave: () => void;
}) {
  const { node, expanded, loading } = treeNode;
  const angleDeg = (angle * 180) / Math.PI - 90;
  const onLeft = angle >= Math.PI;
  const cls =
    "tree__dot" +
    (node.has_children ? " tree__dot--expandable" : "") +
    (expanded ? " tree__dot--expanded" : "") +
    (selected ? " tree__dot--selected" : "") +
    (loading ? " tree__dot--loading" : "");
  const label = truncate(node.name);
  const hover = (e: React.MouseEvent) => onHover(e.clientX, e.clientY);

  // Root sits at the centre with a centred label; others use the standard radial
  // group transform (rotate to the branch angle, translate out to the radius),
  // so the label's rotate(180) on the left half pivots around the node itself.
  if (isRoot) {
    return (
      <g className="tree__node" onClick={onClick} onMouseMove={hover} onMouseLeave={onLeave}>
        <circle cx={0} cy={0} r={r} fill={coverageColor(node, colorKey, ramp, noData)} className={cls} />
        <text className="tree__label tree__label--root" x={0} y={-(r + 7)}>
          {label}
        </text>
      </g>
    );
  }
  return (
    <g
      className="tree__node"
      transform={`rotate(${angleDeg}) translate(${radius} 0)`}
      onClick={onClick}
      onMouseMove={hover}
      onMouseLeave={onLeave}
    >
      <circle cx={0} cy={0} r={r} fill={coverageColor(node, colorKey, ramp, noData)} className={cls} />
      <text
        className="tree__label"
        x={onLeft ? -(r + 5) : r + 5}
        dy="0.32em"
        textAnchor={onLeft ? "end" : "start"}
        transform={onLeft ? "rotate(180)" : undefined}
      >
        {label}
      </text>
    </g>
  );
}

function MoreNode({
  angle,
  radius,
  remaining,
  onClick,
}: {
  angle: number;
  radius: number;
  remaining: number;
  onClick: () => void;
}) {
  const angleDeg = (angle * 180) / Math.PI - 90;
  return (
    <g className="tree__more" transform={`rotate(${angleDeg}) translate(${radius} 0)`} onClick={onClick}>
      <circle cx={0} cy={0} r={8} className="tree__more-dot" />
      <text x={0} y={0} dy="0.32em" textAnchor="middle" className="tree__more-label">
        +{remaining > 99 ? "99+" : remaining}
      </text>
      <title>Load {remaining} more</title>
    </g>
  );
}

/** Brief details for the clicked node, with the explicit path to its dashboard. */
function DetailsPanel({
  node,
  expanded,
  metrics,
  onOpen,
  onToggle,
  onClose,
}: {
  node: TaxonNode;
  expanded: boolean;
  metrics: MetricConfig[];
  onOpen: () => void;
  onToggle: () => void;
  onClose: () => void;
}) {
  return (
    <aside className="tree-panel" aria-label={`Details for ${node.name}`}>
      <button type="button" className="tree-panel__close" onClick={onClose} aria-label="Close details">
        ×
      </button>
      <h3 className="tree-panel__name">{node.name}</h3>
      <p className="tree-panel__sub">
        <span className="rank-badge">{node.rank}</span> {fmt(node.n_rows)} species
      </p>
      <div className="tree-panel__metrics">
        {metrics.map((m) => {
          const r = node.resources[m.key];
          return (
            <div key={m.key} className="tree-panel__metric">
              <span className="tree-panel__mlabel">
                <span className="tree-panel__dot" style={{ background: m.color }} />
                {m.card_title}
              </span>
              <span className="tree-panel__bar">
                <span
                  className="tree-panel__fill"
                  style={{ width: `${Math.min(r.percent, 100)}%`, background: m.color }}
                />
              </span>
              <span className="tree-panel__mval">{fmtPct(r.percent)}%</span>
            </div>
          );
        })}
      </div>
      <div className="tree-panel__actions">
        {node.has_children && (
          <button type="button" className="tree-panel__btn" onClick={onToggle}>
            {expanded ? "Collapse" : "Expand"}
          </button>
        )}
        <button type="button" className="tree-panel__btn tree-panel__btn--primary" onClick={onOpen}>
          Open dashboard →
        </button>
      </div>
    </aside>
  );
}

function Legend({ label, ramp, noData }: { label?: string; ramp: RGB[]; noData: string }) {
  return (
    <div className="tree-legend">
      <span className="tree-legend__title">Colour · {label ?? "coverage"} %</span>
      <span className="tree-legend__ramp">
        <span className="tree-legend__cap">0</span>
        <span
          className="tree-legend__bar"
          style={{ background: `linear-gradient(to right, ${ramp.map(rgbStr).join(", ")})` }}
        />
        <span className="tree-legend__cap">100%</span>
      </span>
      <span className="tree-legend__item">
        <span className="tree-legend__step" style={{ background: noData }} /> no species
      </span>
      <span className="tree-legend__hint">size ∝ species · click a node for details</span>
    </div>
  );
}
