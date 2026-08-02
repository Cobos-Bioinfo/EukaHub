import { hierarchy, treemap, treemapResquarify } from "d3-hierarchy";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { getBreakdown, getBreakdownQuality, getLineage } from "../api/queries";
import type { CladeSummary, TargetRank, TaxonRef } from "../api/types";
import { useAsync } from "../hooks/useAsync";
import { fmt, fmtBp, fmtPct } from "../lib/format";
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
const RANK_PLURAL: Record<string, string> = {
  phylum: "phyla", class: "classes", order: "orders",
  family: "families", genus: "genera", species: "species",
};

// Quality stats per tile, merged from the breakdown-quality endpoint by taxid.
type BucketStats = Record<string, number | null>;

// A lens = what a tile's colour means. Every lens produces one value per tile;
// null = grey (no data). Percentage lenses fill the 0–100 ramp directly;
// "relative" (magnitude) lenses normalise to the largest tile in view, so the
// legend shows that max. Colour is always one blue ramp — switching lenses
// re-paints the same tiles and the shift in pattern is the insight.
const RAMP_HUE = "#1f6feb";
type Scale = "pct" | "relative";
interface Lens {
  key: string;
  label: string;
  scale: Scale;
  value: (n: CladeSummary, q?: BucketStats) => number | null;
  legend: string;
  fmt?: (v: number) => string; // relative lenses: how the legend max is rendered
}

function contiguityPct(n: CladeSummary): number | null {
  const c = n.composition;
  const total = c.complete + c.chromosome + c.scaffold + c.contig;
  return total > 0 ? ((c.complete + c.chromosome) / total) * 100 : null;
}

const COVERAGE_LENSES: Lens[] = [
  { key: "ass", label: "Assemblies", scale: "pct", value: (n) => (n.resources.ass.covered > 0 ? n.resources.ass.percent : null), legend: "% of species with a genome assembly" },
  { key: "ann", label: "Annotations", scale: "pct", value: (n) => (n.resources.ann.covered > 0 ? n.resources.ann.percent : null), legend: "% of species with an annotation" },
  { key: "rna", label: "RNA-Seq", scale: "pct", value: (n) => (n.resources.rna.covered > 0 ? n.resources.rna.percent : null), legend: "% of species with RNA-Seq" },
];
const QUALITY_LENSES: Lens[] = [
  { key: "contig", label: "Contiguity", scale: "pct", value: (n) => contiguityPct(n), legend: "% of assemblies chromosome-level or better" },
  { key: "busco", label: "BUSCO", scale: "pct", value: (_n, q) => q?.busco ?? null, legend: "best BUSCO completeness among the group's annotations" },
  { key: "genes", label: "Genes", scale: "relative", fmt: (v) => fmt(Math.round(v)), value: (_n, q) => q?.genes ?? null, legend: "median protein-coding gene count (darker = more)" },
  { key: "genome", label: "Genome size", scale: "relative", fmt: fmtBp, value: (_n, q) => q?.genome_size ?? null, legend: "median assembly length (darker = larger)" },
];
const LENSES = [...COVERAGE_LENSES, ...QUALITY_LENSES];
const QUALITY_KEYS = new Set(["contig", "busco", "genes", "genome"]);

type SizeBy = "species" | "assemblies";
const sizeValue = (n: CladeSummary, by: SizeBy): number =>
  Math.max(0, by === "species" ? n.n_rows : n.resources.ass.total);

interface Tile {
  node: CladeSummary;
  x0: number; y0: number; x1: number; y1: number;
  fill: string;
  ink: string;
}
interface Hover {
  node: CladeSummary;
  q?: BucketStats;
  x: number;
  y: number;
}

/** The reimagined rank breakdown as a click-to-drill "data landscape". Each tile
 *  is a subgroup at the next rank down; area ∝ size (species / assemblies),
 *  colour ∝ a lens (coverage or quality) on one theme-aware ramp. Big + pale = a
 *  large group with little data (the gap). Click to dive in; the breadcrumb
 *  climbs back out. No rank dropdown — depth is the rank. */
export default function BreakdownLab() {
  const { taxid: taxidParam } = useParams();
  const routeTaxid = Number(taxidParam);
  const navigate = useNavigate();

  const [trail, setTrail] = useState<TaxonRef[]>([]);
  const [lensKey, setLensKey] = useState("ass");
  const [sizeBy, setSizeBy] = useState<SizeBy>("species");
  const [hover, setHover] = useState<Hover | null>(null);

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
        ? getBreakdown(focus.taxid, { rank: targetRank, sort: "n_rows", exclude_empty: false, limit: 250 })
        : Promise.resolve(null),
    [focus?.taxid, targetRank],
  );
  // The quality lenses ride a second, independent fetch so the map paints
  // immediately from the breakdown and the quality colours fill in when ready.
  const quality = useAsync(
    () => (focus && targetRank ? getBreakdownQuality(focus.taxid, targetRank) : Promise.resolve(null)),
    [focus?.taxid, targetRank],
  );
  const qmap = useMemo(() => {
    const m = new Map<number, BucketStats>();
    for (const b of quality.data ?? []) {
      const o: BucketStats = {};
      for (const s of b.stats) o[s.key] = s.value;
      m.set(b.taxid, o);
    }
    return m;
  }, [quality.data]);

  const dark = useTheme() === "dark";
  const ramp = useMemo(() => buildRamp(RAMP_HUE, dark), [dark]);
  const noData = dark ? NO_DATA_DARK : NO_DATA_LIGHT;
  const lens = LENSES.find((l) => l.key === lensKey) ?? LENSES[0];
  const qLoading = QUALITY_KEYS.has(lens.key) && lens.key !== "contig" && quality.loading;

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
  const { tiles, maxRaw } = useMemo<{ tiles: Tile[]; maxRaw: number }>(() => {
    const withData = items.filter((n) => sizeValue(n, sizeBy) > 0);
    if (withData.length === 0) return { tiles: [], maxRaw: 0 };
    // Max raw value for a relative (magnitude) lens, to normalise colour + legend.
    let maxRaw = 0;
    if (lens.scale === "relative") {
      for (const n of withData) {
        const v = lens.value(n, qmap.get(n.taxid));
        if (v != null && v > maxRaw) maxRaw = v;
      }
    }
    type Datum = { children?: CladeSummary[] } & Partial<CladeSummary>;
    const root = hierarchy<Datum>({ children: withData } as Datum)
      .sum((d) => (Array.isArray(d.children) ? 0 : sizeValue(d as CladeSummary, sizeBy)))
      .sort((a, b) => (b.value ?? 0) - (a.value ?? 0));
    const laidOut = treemap<Datum>()
      .tile(treemapResquarify)
      .size([size.w, size.h])
      .paddingInner(3)
      .round(true)(root);
    const tiles = laidOut.leaves().map((l) => {
      const node = l.data as CladeSummary;
      const raw = lens.value(node, qmap.get(node.taxid));
      const norm = raw == null ? null : lens.scale === "relative" ? (maxRaw > 0 ? (raw / maxRaw) * 100 : 0) : raw;
      const rgb = norm == null ? null : rampRgb(norm, ramp);
      return {
        node,
        x0: l.x0 ?? 0, y0: l.y0 ?? 0, x1: l.x1 ?? 0, y1: l.y1 ?? 0,
        fill: rgb ? rgbStr(rgb) : noData,
        ink: luminance(rgb ?? (dark ? [51, 58, 68] : [211, 216, 223])) < 0.55 ? "#fff" : "#0b0b0b",
      };
    });
    return { tiles, maxRaw };
  }, [items, sizeBy, size.w, size.h, ramp, noData, dark, lens, qmap]);

  const drill = (n: CladeSummary) => {
    if (nextRank(n.rank)) setTrail((t) => [...t, { taxid: n.taxid, name: n.name, rank: n.rank }]);
    else navigate(`/clade/${n.taxid}`);
  };

  if (!Number.isInteger(routeTaxid) || routeTaxid <= 0)
    return <p className="notice notice--error">Invalid taxon id.</p>;

  const rankNoun = targetRank ?? "group";
  const rankPlural = targetRank ? (RANK_PLURAL[targetRank] ?? `${targetRank}s`) : "subgroups";
  const legendMax = lens.scale === "relative" ? (lens.fmt ?? fmt)(maxRaw) : "100%";

  return (
    <section className="bmap-page">
      <header className="bmap-page__head">
        <h1 className="bmap-page__title">
          Where&apos;s the data? <span className="bmap-page__beta">prototype</span>
        </h1>
        <p className="bmap-page__sub">
          {focus ? (
            <>
              <strong>{focus.name}</strong> split into its {rankPlural}. Each tile is one {rankNoun}
              &nbsp;— <strong>size</strong> shows how many {sizeBy} it has, <strong>colour</strong> shows{" "}
              {lens.legend}. A big pale tile is a large group with little data. <strong>Click</strong> a
              tile to dive one rank deeper; use the trail above to climb back.
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
              <button type="button" className="bmap-crumb__link" onClick={() => setTrail((tr) => tr.slice(0, i + 1))}>
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
          <div className="tree-controls__seg" role="group" aria-label="Colour tiles by coverage">
            {COVERAGE_LENSES.map((l) => (
              <LensButton key={l.key} lens={l} active={l.key === lensKey} onClick={() => setLensKey(l.key)} />
            ))}
          </div>
          <div className="tree-controls__seg" role="group" aria-label="Colour tiles by quality">
            {QUALITY_LENSES.map((l) => (
              <LensButton key={l.key} lens={l} active={l.key === lensKey} onClick={() => setLensKey(l.key)} />
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
                onMouseMove={(e) => setHover({ node: t.node, q: qmap.get(t.node.taxid), x: e.clientX, y: e.clientY })}
                onMouseLeave={() => setHover(null)}
                aria-label={`${t.node.name}, ${fmt(t.node.n_rows)} species`}
              >
                {labelled && (
                  <span className="bmap-tile__body">
                    <span className="bmap-tile__name">{t.node.name}</span>
                    <span className="bmap-tile__stat">
                      {sizeBy === "species" ? `${fmt(t.node.n_rows)} sp` : `${fmt(t.node.resources.ass.total)} asm`}
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
            <span className="bmap-legend__title">
              {lens.label}
              {qLoading && <span className="bmap-legend__loading"> · computing…</span>}
            </span>
            <span className="bmap-legend__ramp">
              <span className="bmap-legend__cap">0</span>
              <span
                className="bmap-legend__bar"
                style={{ background: `linear-gradient(to right, ${ramp.map(rgbStr).join(", ")})` }}
              />
              <span className="bmap-legend__cap">{legendMax}</span>
            </span>
            <span className="bmap-legend__hint">
              <span className="bmap-legend__chip" style={{ background: noData }} /> no data
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

      {hover && <TileTooltip hover={hover} />}
    </section>
  );
}

function LensButton({ lens, active, onClick }: { lens: Lens; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      className={"seg-btn" + (active ? " seg-btn--on" : "")}
      onClick={onClick}
      title={lens.legend}
    >
      {lens.label}
    </button>
  );
}

/** Rich hover card: everything the tile encodes, plus the numbers it doesn't. */
function TileTooltip({ hover }: { hover: Hover }) {
  const { node, q } = hover;
  const contig = contiguityPct(node);
  return (
    <div className="chart-tip bmap-tip" style={{ left: hover.x + 14, top: hover.y + 14 }} role="tooltip">
      <div className="chart-tip__name">{node.name}</div>
      <div className="chart-tip__sub">
        {node.rank} · {fmt(node.n_rows)} species
      </div>

      <div className="bmap-tip__group">Coverage</div>
      <CovRow label="Assemblies" r={node.resources.ass} />
      <CovRow label="Annotations" r={node.resources.ann} />
      <CovRow label="RNA-Seq" r={node.resources.rna} />
      <CovRow label="Long-read RNA" r={node.resources.lng} />

      <div className="bmap-tip__group">Quality</div>
      <ValRow label="Chromosome-level+" value={contig != null ? `${fmtPct(contig)}%` : "—"} />
      <ValRow label="Best BUSCO" value={q?.busco != null ? `${fmtPct(q.busco)}%` : "—"} />
      <ValRow label="Median genes" value={q?.genes != null ? fmt(Math.round(q.genes)) : "—"} />
      <ValRow label="Median genome" value={q?.genome_size != null ? fmtBp(q.genome_size) : "—"} />
      {node.composition.reference > 0 && (
        <ValRow label="Reference genomes" value={fmt(node.composition.reference)} />
      )}
    </div>
  );
}

function CovRow({ label, r }: { label: string; r: { covered: number; total: number; percent: number } }) {
  return (
    <div className="chart-tip__row">
      <span className="chart-tip__label">{label}</span>
      <span className="chart-tip__val">
        {r.total > 0 ? `${fmt(r.total)} · ${fmtPct(r.percent)}%` : "—"}
      </span>
    </div>
  );
}

function ValRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="chart-tip__row">
      <span className="chart-tip__label">{label}</span>
      <span className="chart-tip__val">{value}</span>
    </div>
  );
}
