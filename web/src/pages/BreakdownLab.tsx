import { hierarchy, treemap, treemapResquarify } from "d3-hierarchy";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { getBreakdown, getLineage } from "../api/queries";
import type { CladeSummary, TargetRank, TaxonRef } from "../api/types";
import { useAsync } from "../hooks/useAsync";
import { fmt, fmtPct } from "../lib/format";
import { NO_DATA_DARK, NO_DATA_LIGHT, buildRamp, luminance, rampRgb, rgbStr } from "../lib/ramp";
import { useTheme } from "../lib/theme";

// Drilling jumps to the next *meaningful* rank, not the immediate adjacency child
// (taxonomy hides the interesting split several rankless clades deep — Mammalia →
// Theria → Eutheria → ... → orders). So the map always shows a real comparison,
// and the rank stays implicit in the drill depth (no rank dropdown).
const ALLOWED: TargetRank[] = ["phylum", "class", "order", "family", "genus", "species"];
const LADDER = [
  "domain", "superkingdom", "kingdom", "subkingdom", "phylum", "subphylum",
  "superclass", "class", "subclass", "infraclass", "superorder", "order",
  "suborder", "infraorder", "superfamily", "family", "subfamily", "tribe",
  "genus", "subgenus", "species",
];
function nextRank(rank: string): TargetRank | null {
  const i = LADDER.indexOf(rank);
  for (let j = i + 1; j < LADDER.length; j++) {
    if (ALLOWED.includes(LADDER[j] as TargetRank)) return LADDER[j] as TargetRank;
  }
  return null;
}

// The lens = what a tile's colour means. Every lens maps to 0–100 on one blue
// ramp (clarity: more blue = more of the selected thing; grey = none), so
// switching lenses re-paints the same tiles and the pattern shift *is* the
// insight. "Quality" surfaces the enrichment Annotrieve doesn't frame this way.
const RAMP_HUE = "#1f6feb";

function contiguityPct(n: CladeSummary): number {
  const c = n.composition;
  const total = c.complete + c.chromosome + c.scaffold + c.contig;
  return total > 0 ? ((c.complete + c.chromosome) / total) * 100 : 0;
}

interface Lens {
  key: string;
  label: string;
  value: (n: CladeSummary) => number;
  legend: string;
}
const LENSES: Lens[] = [
  { key: "ass", label: "Assemblies", value: (n) => n.resources.ass.percent, legend: "% of species with a genome assembly" },
  { key: "ann", label: "Annotations", value: (n) => n.resources.ann.percent, legend: "% of species with an annotation" },
  { key: "rna", label: "RNA-Seq", value: (n) => n.resources.rna.percent, legend: "% of species with RNA-Seq" },
  { key: "quality", label: "Quality", value: contiguityPct, legend: "% of assemblies chromosome-level or better" },
];

type SizeBy = "species" | "assemblies";
const sizeValue = (n: CladeSummary, by: SizeBy): number =>
  Math.max(0, by === "species" ? n.n_rows : n.resources.ass.total);

interface Tile {
  node: CladeSummary;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  fill: string;
  ink: string;
}
interface Hover {
  node: CladeSummary;
  x: number;
  y: number;
}

/** PROTOTYPE — the reimagined rank breakdown as a click-to-drill "data
 *  landscape". Each tile is a subgroup at the next rank down; area ∝ a chosen
 *  size (species / assemblies), colour ∝ a chosen lens (coverage / quality).
 *  Big + pale = a large group with little data (the gap). Click to dive in;
 *  the breadcrumb climbs back out. No rank dropdown — depth is the rank. */
export default function BreakdownLab() {
  const { taxid: taxidParam } = useParams();
  const routeTaxid = Number(taxidParam);
  const navigate = useNavigate();

  const [trail, setTrail] = useState<TaxonRef[]>([]);
  const [lensKey, setLensKey] = useState("ass");
  const [sizeBy, setSizeBy] = useState<SizeBy>("species");
  const [hover, setHover] = useState<Hover | null>(null);

  // Seed the trail with the route root's own ref (name + rank), needed to pick
  // the first target rank. Resets when the route taxon changes.
  const lineage = useAsync(() => getLineage(routeTaxid), [routeTaxid]);
  useEffect(() => {
    if (lineage.data)
      setTrail([{ taxid: lineage.data.taxid, name: lineage.data.name, rank: lineage.data.rank }]);
  }, [lineage.data]);

  const focus = trail.length ? trail[trail.length - 1] : null;
  const targetRank = focus ? nextRank(focus.rank) : null;

  const bd = useAsync(
    () =>
      focus && targetRank
        ? getBreakdown(focus.taxid, {
            rank: targetRank,
            sort: "n_rows",
            exclude_empty: false,
            limit: 250,
          })
        : Promise.resolve(null),
    [focus?.taxid, targetRank],
  );

  const dark = useTheme() === "dark";
  const ramp = useMemo(() => buildRamp(RAMP_HUE, dark), [dark]);
  const noData = dark ? NO_DATA_DARK : NO_DATA_LIGHT;
  const lens = LENSES.find((l) => l.key === lensKey) ?? LENSES[0];

  const boxRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 960, h: 560 });
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const cr = entries[0]?.contentRect;
      if (cr && cr.width > 0 && cr.height > 0)
        setSize({ w: Math.round(cr.width), h: Math.round(cr.height) });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const items = bd.data?.items ?? [];
  const tiles = useMemo<Tile[]>(() => {
    const withData = items.filter((n) => sizeValue(n, sizeBy) > 0);
    if (withData.length === 0) return [];
    type Datum = { children?: CladeSummary[] } & Partial<CladeSummary>;
    const root = hierarchy<Datum>({ children: withData } as Datum)
      .sum((d) => (Array.isArray(d.children) ? 0 : sizeValue(d as CladeSummary, sizeBy)))
      .sort((a, b) => (b.value ?? 0) - (a.value ?? 0));
    const laidOut = treemap<Datum>()
      .tile(treemapResquarify)
      .size([size.w, size.h])
      .paddingInner(3)
      .round(true)(root);
    return laidOut.leaves().map((l) => {
      const node = l.data as CladeSummary;
      const pct = lens.value(node);
      const hasAssemblies = node.resources.ass.total > 0;
      const rgb = pct > 0 || hasAssemblies ? rampRgb(pct, ramp) : null;
      return {
        node,
        x0: l.x0 ?? 0,
        y0: l.y0 ?? 0,
        x1: l.x1 ?? 0,
        y1: l.y1 ?? 0,
        fill: rgb ? rgbStr(rgb) : noData,
        ink: luminance(rgb ?? (dark ? [51, 58, 68] : [211, 216, 223])) < 0.55 ? "#fff" : "#0b0b0b",
      };
    });
  }, [items, sizeBy, size.w, size.h, ramp, noData, dark, lens]);

  const drill = (n: CladeSummary) => {
    if (nextRank(n.rank)) setTrail((t) => [...t, { taxid: n.taxid, name: n.name, rank: n.rank }]);
    else navigate(`/clade/${n.taxid}`);
  };

  if (!Number.isInteger(routeTaxid) || routeTaxid <= 0)
    return <p className="notice notice--error">Invalid taxon id.</p>;

  const RANK_PLURAL: Record<string, string> = {
    phylum: "phyla",
    class: "classes",
    order: "orders",
    family: "families",
    genus: "genera",
    species: "species",
  };
  const rankNoun = targetRank ?? "group";
  const rankPlural = targetRank ? (RANK_PLURAL[targetRank] ?? `${targetRank}s`) : "subgroups";

  return (
    <section className="bmap-page">
      <header className="bmap-page__head">
        <h1 className="bmap-page__title">
          Where&apos;s the data? <span className="bmap-page__beta">prototype</span>
        </h1>
        <p className="bmap-page__sub">
          {focus ? (
            <>
              <strong>{focus.name}</strong> broken into {rankPlural}. Each tile is one {rankNoun}:
              bigger = more {sizeBy}, bluer = more {lens.label.toLowerCase()}. A big pale tile is a
              large group nobody has sequenced. Click a tile to dive one rank deeper.
            </>
          ) : (
            "Loading…"
          )}
        </p>
      </header>

      <nav className="bmap-crumbs" aria-label="Drill path">
        {trail.map((t, i) => (
          <span key={t.taxid} className="bmap-crumb">
            {i > 0 && <span className="bmap-crumb__sep">›</span>}
            {i < trail.length - 1 ? (
              <button
                type="button"
                className="bmap-crumb__link"
                onClick={() => setTrail((tr) => tr.slice(0, i + 1))}
              >
                {t.name}
              </button>
            ) : (
              <span className="bmap-crumb__here">
                {t.name} <span className="bmap-crumb__rank">{t.rank}</span>
              </span>
            )}
          </span>
        ))}
      </nav>

      <div className="bmap-controls">
        <div className="bmap-ctl">
          <span className="tree-controls__label">Colour by</span>
          <div className="tree-controls__seg" role="group" aria-label="Colour tiles by">
            {LENSES.map((l) => (
              <button
                key={l.key}
                type="button"
                className={"seg-btn" + (l.key === lensKey ? " seg-btn--on" : "")}
                onClick={() => setLensKey(l.key)}
              >
                {l.label}
              </button>
            ))}
          </div>
        </div>
        <div className="bmap-ctl">
          <span className="tree-controls__label">Size by</span>
          <div className="tree-controls__seg" role="group" aria-label="Size tiles by">
            {(["species", "assemblies"] as SizeBy[]).map((s) => (
              <button
                key={s}
                type="button"
                className={"seg-btn" + (s === sizeBy ? " seg-btn--on" : "")}
                onClick={() => setSizeBy(s)}
              >
                {s === "species" ? "Species" : "Assemblies"}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="bmap" ref={boxRef}>
        {lineage.loading || bd.loading ? (
          <p className="notice">Mapping…</p>
        ) : bd.error ? (
          <p className="notice notice--error">{bd.error}</p>
        ) : !targetRank ? (
          <p className="notice">
            {focus?.name} is a {focus?.rank} — the finest rank. Open its{" "}
            <button className="bmap-crumb__link" type="button" onClick={() => navigate(`/clade/${focus?.taxid}`)}>
              dashboard
            </button>{" "}
            for its records.
          </p>
        ) : tiles.length === 0 ? (
          <p className="notice">
            No {rankPlural} to map by {sizeBy} under {focus?.name}.
            {sizeBy === "assemblies" && " Try sizing by species."}
          </p>
        ) : (
          tiles.map((t) => {
            const w = t.x1 - t.x0;
            const h = t.y1 - t.y0;
            const labelled = w > 54 && h > 30;
            const canDrill = !!nextRank(t.node.rank);
            return (
              <button
                key={t.node.taxid}
                type="button"
                className="bmap-tile"
                style={{ left: t.x0, top: t.y0, width: w, height: h, background: t.fill, color: t.ink }}
                onClick={() => drill(t.node)}
                onMouseMove={(e) => setHover({ node: t.node, x: e.clientX, y: e.clientY })}
                onMouseLeave={() => setHover(null)}
                aria-label={`${t.node.name}, ${fmt(t.node.n_rows)} species, ${fmtPct(lens.value(t.node))}% ${lens.label}`}
              >
                {labelled && (
                  <span className="bmap-tile__body">
                    <span className="bmap-tile__name">{t.node.name}</span>
                    <span className="bmap-tile__stat">
                      {sizeBy === "species"
                        ? `${fmt(t.node.n_rows)} sp`
                        : `${fmt(t.node.resources.ass.total)} asm`}
                    </span>
                  </span>
                )}
                {canDrill && labelled && <span className="bmap-tile__dive" aria-hidden="true">⤢</span>}
              </button>
            );
          })
        )}

        {targetRank && tiles.length > 0 && (
          <div className="bmap-legend">
            <span className="bmap-legend__title">{lens.label}</span>
            <span className="bmap-legend__ramp">
              <span className="bmap-legend__cap">0</span>
              <span
                className="bmap-legend__bar"
                style={{ background: `linear-gradient(to right, ${ramp.map(rgbStr).join(", ")})` }}
              />
              <span className="bmap-legend__cap">100%</span>
            </span>
            <span className="bmap-legend__hint">
              <span className="bmap-legend__chip" style={{ background: noData }} /> no data · {lens.legend}
            </span>
          </div>
        )}
      </div>

      {bd.data && (
        <p className="bmap-foot">
          {fmt(bd.data.returned)}
          {bd.data.total_matches > bd.data.returned ? ` of ${fmt(bd.data.total_matches)}` : ""}{" "}
          {rankPlural}. Click a group with subgroups to dive in; click a genus or species to open its
          dashboard.
        </p>
      )}

      {hover && (
        <div className="chart-tip bmap-tip" style={{ left: hover.x + 14, top: hover.y + 14 }} role="tooltip">
          <div className="chart-tip__name">{hover.node.name}</div>
          <div className="chart-tip__sub">
            {hover.node.rank} · {fmt(hover.node.n_rows)} species
          </div>
          <TipRow label="Assemblies" r={hover.node.resources.ass} />
          <TipRow label="Annotations" r={hover.node.resources.ann} />
          <TipRow label="RNA-Seq" r={hover.node.resources.rna} />
          <div className="chart-tip__row">
            <span className="chart-tip__label">Chromosome-level+</span>
            <span className="chart-tip__val">{fmtPct(contiguityPct(hover.node))}%</span>
          </div>
        </div>
      )}
    </section>
  );
}

function TipRow({ label, r }: { label: string; r: { covered: number; total: number; percent: number } }) {
  return (
    <div className="chart-tip__row">
      <span className="chart-tip__label">{label}</span>
      <span className="chart-tip__val">
        {fmt(r.total)} · {fmtPct(r.percent)}%
      </span>
    </div>
  );
}
