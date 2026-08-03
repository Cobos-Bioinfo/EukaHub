import { hierarchy, treemap, treemapResquarify } from "d3-hierarchy";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { exportTsvUrl, getBreakdown, getBreakdownQuality, getLineage } from "../api/queries";
import type { CladeSummary, TargetRank, TaxonRef } from "../api/types";
import { useAsync } from "../hooks/useAsync";
import { fmt, fmtBp, fmtPct } from "../lib/format";
import { NO_DATA_DARK, NO_DATA_LIGHT, buildRamp, luminance, rampRgb, rgbStr } from "../lib/ramp";
import { useTheme } from "../lib/theme";

// Drilling jumps to the next meaningful rank, not the immediate adjacency child.
// Taxonomy hides the interesting split several rankless clades deep (Mammalia
// holds one child, Theria, that carries almost every species), so a map of
// immediate children would be one giant tile. Jumping to the next canonical rank
// keeps every level a real comparison and lets the rank stay implicit in the
// drill depth, which is what lets us drop the rank dropdown.
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

// The rank to break a focus down into. When the focus carries a canonical rank
// we take the next canonical rank below it. But many taxa are rankless (rank
// "clade" or "no rank": Eutheria, Bilateria, Opisthokonta, ...), and for those
// nextRank("clade") would fall through to phylum — wrong for a clade that sits
// *below* phylum (Eutheria is under class Mammalia and has no phylum
// descendants, only orders). So for a rankless focus we anchor to the deepest
// canonical-ranked ancestor in its lineage and step down from there (Eutheria →
// Mammalia is class → order). A rankless focus above phylum (Opisthokonta,
// whose deepest canonical ancestor is a domain) still resolves to phylum, which
// is non-empty there. `lineage` is the focus's root→node chain (inclusive);
// drilled tiles are always canonical ranks, so they never need it.
function targetRankFor(focus: TaxonRef, lineage: string[]): TargetRank | null {
  if (LADDER.includes(focus.rank)) return nextRank(focus.rank);
  for (let i = lineage.length - 1; i >= 0; i--) {
    if (LADDER.includes(lineage[i])) return nextRank(lineage[i]);
  }
  return nextRank(focus.rank); // no canonical ancestor → phylum via the -1 path
}
const RANK_PLURAL: Record<string, string> = {
  phylum: "phyla", class: "classes", order: "orders",
  family: "families", genus: "genera", species: "species",
};

type BucketStats = Record<string, number | null>;

// A lens sets what a tile's colour means. Each lens returns one value per tile;
// null paints grey (no data). Percentage lenses fill the 0-100 ramp; magnitude
// lenses normalise to the largest tile on screen and show that max in the
// legend. Each lens carries its own hue, so the active ramp signals which lens
// you're reading: the coverage lenses take a member of their resource's colour
// family (matching the cards and the Tree of Life), the quality lenses share one
// purple so "quality" reads as a single dimension. Only one lens shows at a time,
// so the hues are single-hue sequential scales, never a rainbow at once. The
// cards' pale assemblies/RNA-Seq tints have too little tone to fill a treemap, so
// those two are saturated here (keeping the blue/green identity); annotations
// already reads well, so it stays its exact card colour.
const COVERAGE_HUES: Record<string, string> = { ass: "#2f8fd8", ann: "#1f78b4", rna: "#55ad39" };
const QUALITY_HUE = "#6a3d9a"; // one hue shared by every quality lens
type Scale = "pct" | "relative";
interface Lens {
  key: string;
  label: string;
  hue: string;
  scale: Scale;
  value: (n: CladeSummary, q?: BucketStats) => number | null;
  legend: string;
  fmt?: (v: number) => string;
  /** Fuller name for the legend/list where the compact button label is terse. */
  legendLabel?: string;
}

function contiguityPct(n: CladeSummary): number | null {
  const c = n.composition;
  const total = c.complete + c.chromosome + c.scaffold + c.contig;
  return total > 0 ? ((c.complete + c.chromosome) / total) * 100 : null;
}

const COVERAGE_LENSES: Lens[] = [
  { key: "ass", label: "Assemblies", hue: COVERAGE_HUES.ass, scale: "pct", value: (n) => (n.resources.ass.covered > 0 ? n.resources.ass.percent : null), legend: "share of species with a genome assembly" },
  { key: "ann", label: "Annotations", hue: COVERAGE_HUES.ann, scale: "pct", value: (n) => (n.resources.ann.covered > 0 ? n.resources.ann.percent : null), legend: "share of species with an annotation" },
  { key: "rna", label: "RNA-Seq", hue: COVERAGE_HUES.rna, scale: "pct", value: (n) => (n.resources.rna.covered > 0 ? n.resources.rna.percent : null), legend: "share of species with RNA-Seq" },
];
const QUALITY_LENSES: Lens[] = [
  { key: "contig", label: "Contiguity", hue: QUALITY_HUE, scale: "pct", value: (n) => contiguityPct(n), legend: "share of assemblies at chromosome level or better" },
  { key: "busco", label: "BUSCO", hue: QUALITY_HUE, scale: "pct", value: (_n, q) => q?.busco ?? null, legend: "best BUSCO completeness across the group's annotations" },
  { key: "genes", label: "Coding genes", legendLabel: "Protein-coding genes", hue: QUALITY_HUE, scale: "relative", fmt: (v) => fmt(Math.round(v)), value: (_n, q) => q?.genes ?? null, legend: "median protein-coding gene count (darker means more)" },
  { key: "genome", label: "Genome size", hue: QUALITY_HUE, scale: "relative", fmt: fmtBp, value: (_n, q) => q?.genome_size ?? null, legend: "median assembly length (darker means larger)" },
];
const LENSES = [...COVERAGE_LENSES, ...QUALITY_LENSES];
const NEEDS_QUALITY = new Set(["busco", "genes", "genome"]);

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

/** The drill trail (root → focus) and the moves over it. On the standalone page
 *  it lives in the URL as `?d=t1-t2-t3` (the taxids drilled below the root), so
 *  the browser back/forward buttons walk the drill and a link is shareable; the
 *  embedded variant keeps it in component state so it never clutters the
 *  dashboard URL. Trail entries need a name + rank (breadcrumb label + rank
 *  stepping): an in-session drill carries them straight from the clicked tile,
 *  and a fresh deep-link load resolves any still-unknown taxids with one lineage
 *  fetch of the focus (every drilled node is one of its ancestors). */
function useDrillTrail(root: TaxonRef, rootLineage: TaxonRef[] | undefined, syncUrl: boolean) {
  const [searchParams, setSearchParams] = useSearchParams();
  const [stateTrail, setStateTrail] = useState<TaxonRef[]>([root]);
  const [clicked, setClicked] = useState<Record<number, TaxonRef>>({});

  // Embedded variant only: reset to the new root when the parent swaps clade.
  useEffect(() => {
    if (!syncUrl) setStateTrail([root]);
  }, [root.taxid, syncUrl]); // eslint-disable-line react-hooks/exhaustive-deps

  const drillTaxids = useMemo(() => {
    if (!syncUrl) return [];
    return (searchParams.get("d") ?? "")
      .split("-")
      .map(Number)
      .filter((n) => Number.isInteger(n) && n > 0);
  }, [syncUrl, searchParams]);

  const focusTaxid = drillTaxids.length ? drillTaxids[drillTaxids.length - 1] : root.taxid;
  // Names/ranks we already hold: the root, its lineage, and tiles clicked this
  // session. Anything left is a deep-link node we must look up.
  const known = useMemo(() => {
    const m = new Map<number, TaxonRef>([[root.taxid, root]]);
    for (const t of rootLineage ?? []) m.set(t.taxid, t);
    for (const t of Object.values(clicked)) m.set(t.taxid, t);
    return m;
  }, [root, rootLineage, clicked]);
  const needLookup = syncUrl && drillTaxids.some((id) => !known.has(id));
  const recon = useAsync(
    () => (needLookup ? getLineage(focusTaxid) : Promise.resolve(null)),
    [needLookup, focusTaxid],
  );

  const trail = useMemo<TaxonRef[]>(() => {
    if (!syncUrl) return stateTrail;
    const fetched = new Map<number, TaxonRef>();
    for (const t of recon.data?.lineage ?? []) fetched.set(t.taxid, t);
    const out: TaxonRef[] = [root];
    for (const id of drillTaxids) {
      const ref = known.get(id) ?? fetched.get(id);
      if (!ref) break; // still resolving — stop at what we can name
      out.push(ref);
    }
    return out;
  }, [syncUrl, stateTrail, root, drillTaxids, known, recon.data]);

  // True while a deep-link trail is still being named (hold the breakdown fetch).
  const resolving = syncUrl && trail.length < drillTaxids.length + 1;

  const drillTo = (n: CladeSummary) => {
    const ref: TaxonRef = { taxid: n.taxid, name: n.name, rank: n.rank };
    if (!syncUrl) {
      setStateTrail((t) => [...t, ref]);
      return;
    }
    setClicked((c) => ({ ...c, [n.taxid]: ref }));
    setSearchParams(
      (p) => {
        const q = new URLSearchParams(p);
        q.set("d", [...drillTaxids, n.taxid].join("-"));
        return q;
      },
      { replace: false },
    );
  };

  // Truncate the trail to keep entries [0..i] (i is a trail index; 0 = root).
  const truncateTo = (i: number) => {
    if (!syncUrl) {
      setStateTrail((tr) => tr.slice(0, i + 1));
      return;
    }
    const keep = drillTaxids.slice(0, i); // trail index i keeps i drilled taxids
    setSearchParams((p) => {
      const q = new URLSearchParams(p);
      if (keep.length) q.set("d", keep.join("-"));
      else q.delete("d");
      return q;
    });
  };

  return { trail, resolving, drillTo, truncateTo };
}

/** The rank breakdown as a click-to-drill "data landscape". Each tile is a
 *  subgroup at the next rank down; area is a chosen size (species or assemblies),
 *  colour is a chosen lens (coverage or quality) on one theme-aware ramp. Big and
 *  pale means a large group with little data. Reusable: the dashboard embeds it
 *  (variant "embed", with a full-screen link), the standalone page renders it
 *  tall (variant "page"). Seeded from `root` so it needs no lineage fetch. */
export default function BreakdownMap({
  root,
  rootLineage,
  heading,
  variant = "page",
}: {
  root: TaxonRef;
  /** The root's root→node lineage (inclusive), used to pick the breakdown rank
   *  when the root is rankless. Optional: an empty/late lineage just falls back
   *  to phylum, self-correcting once it loads. */
  rootLineage?: TaxonRef[];
  heading: string;
  variant?: "page" | "embed";
}) {
  const navigate = useNavigate();
  const { trail, resolving, drillTo, truncateTo } = useDrillTrail(root, rootLineage, variant === "page");
  const [lensKey, setLensKey] = useState("ass");
  const [sizeBy, setSizeBy] = useState<SizeBy>("species");
  const [hover, setHover] = useState<Hover | null>(null);

  const focus = trail[trail.length - 1];
  const rootRanks = useMemo(() => (rootLineage ?? []).map((t) => t.rank), [rootLineage]);
  const targetRank = targetRankFor(focus, rootRanks);

  const bd = useAsync(
    () => (targetRank && !resolving ? getBreakdown(focus.taxid, { rank: targetRank, sort: "n_rows", exclude_empty: false, limit: 250 }) : Promise.resolve(null)),
    [focus.taxid, targetRank, resolving],
  );
  const quality = useAsync(
    () => (targetRank && !resolving ? getBreakdownQuality(focus.taxid, targetRank) : Promise.resolve(null)),
    [focus.taxid, targetRank, resolving],
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
  const lens = LENSES.find((l) => l.key === lensKey) ?? LENSES[0];
  const ramp = useMemo(() => buildRamp(lens.hue, dark), [lens.hue, dark]);
  const noData = dark ? NO_DATA_DARK : NO_DATA_LIGHT;
  const qWaiting = NEEDS_QUALITY.has(lens.key) && quality.loading;

  const boxRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 960, h: 480 });
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const cr = entries[0]?.contentRect;
      if (cr && cr.width > 0 && cr.height > 0) setSize({ w: Math.round(cr.width), h: Math.round(cr.height) });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const items = bd.data?.items ?? [];
  const { tiles, maxRaw } = useMemo<{ tiles: Tile[]; maxRaw: number }>(() => {
    const withData = items.filter((n) => sizeValue(n, sizeBy) > 0);
    if (withData.length === 0) return { tiles: [], maxRaw: 0 };
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

  const activate = (n: CladeSummary) => {
    if (nextRank(n.rank)) drillTo(n);
    else navigate(`/clade/${n.taxid}`);
  };

  const rankNoun = targetRank ?? "group";
  const rankPlural = targetRank ? (RANK_PLURAL[targetRank] ?? `${targetRank}s`) : "subgroups";
  const legendMax = lens.scale === "relative" ? (lens.fmt ?? fmt)(maxRaw) : "100%";
  const capped = bd.data ? bd.data.total_matches > bd.data.returned : false;
  const Heading = variant === "page" ? "h1" : "h2";

  return (
    <section className={"bmap-block bmap-block--" + variant} aria-label={heading}>
      <header className="bmap-block__head">
        <div>
          <Heading className="bmap-block__title">{heading}</Heading>
          {targetRank && (
            <p className="bmap-block__sub">
              Tile size is the number of {sizeBy}; colour shows {lens.legend}. The big pale tiles are
              the gaps: large groups with little data. Click a tile to go deeper, or use the trail to
              come back.
            </p>
          )}
        </div>
        <div className="bmap-actions">
          <Link className="dl" to={`/clade/${focus.taxid}`}>
            Open {focus.name}
          </Link>
          {variant === "embed" && (
            <Link className="dl" to={`/map/${focus.taxid}`}>
              Full screen
            </Link>
          )}
          {targetRank && (
            <a className="dl" href={exportTsvUrl(focus.taxid, { rank: targetRank })}>
              Download TSV
            </a>
          )}
        </div>
      </header>

      {/* The drill trail is a clickable way back; at the root it's a single node
          the level bar below already names, so show it only once you've drilled. */}
      {trail.length > 1 && (
        <nav className="bmap-crumbs" aria-label="Drill path">
          {trail.map((t, i) => (
            <span key={t.taxid} className="bmap-crumb">
              {i > 0 && <span className="bmap-crumb__sep">›</span>}
              {i < trail.length - 1 ? (
                <button type="button" className="bmap-crumb__link" onClick={() => truncateTo(i)}>
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
      )}

      {targetRank && (
        <div className="bmap-level">
          <span className="bmap-level__part">
            <span className="bmap-level__cap">Viewing</span>
            <strong className="bmap-level__name">{focus.name}</strong>
            <span className="bmap-level__rank">{focus.rank}</span>
          </span>
          <span className="bmap-level__part">
            <span className="bmap-level__cap">broken down by</span>
            <span className="bmap-level__rank bmap-level__rank--now">{rankNoun}</span>
            {bd.data && (
              <span className="bmap-level__count">
                {fmt(bd.data.total_matches)} {bd.data.total_matches === 1 ? "group" : "groups"}
              </span>
            )}
          </span>
        </div>
      )}

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

      <div className={"bmap bmap--" + variant} ref={boxRef}>
        {bd.loading || resolving ? (
          <p className="notice">Mapping…</p>
        ) : bd.error ? (
          <p className="notice notice--error">{bd.error}</p>
        ) : !targetRank ? (
          <p className="notice">
            {focus.name} is a {focus.rank}, the finest rank shown here. Open its{" "}
            <Link to={`/clade/${focus.taxid}`}>dashboard</Link> for its records.
          </p>
        ) : tiles.length === 0 ? (
          <p className="notice">
            No {rankPlural} to map by {sizeBy} under {focus.name}.
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
                title={`${t.node.name} · ${fmt(t.node.n_rows)} species`}
                onClick={() => activate(t.node)}
                onMouseMove={(e) => setHover({ node: t.node, q: qmap.get(t.node.taxid), x: e.clientX, y: e.clientY })}
                onMouseLeave={() => setHover(null)}
                aria-label={`${t.node.name}, ${fmt(t.node.n_rows)} species. ${canDrill ? "Open its subgroups." : "Open its dashboard."}`}
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
              {lens.legendLabel ?? lens.label}
              {qWaiting && <span className="bmap-legend__loading"> · computing…</span>}
            </span>
            <span className="bmap-legend__ramp">
              <span className="bmap-legend__cap">0</span>
              <span className="bmap-legend__bar" style={{ background: `linear-gradient(to right, ${ramp.map(rgbStr).join(", ")})` }} />
              <span className="bmap-legend__cap">{legendMax}</span>
            </span>
            <span className="bmap-legend__hint">
              <span className="bmap-legend__chip" style={{ background: noData }} /> no data
            </span>
          </div>
        )}
      </div>

      {bd.data && targetRank && tiles.length > 0 && (
        <>
          <p className="bmap-foot">
            {capped
              ? `The ${fmt(bd.data.returned)} largest ${rankPlural} by ${sizeBy}, of ${fmt(bd.data.total_matches)}.`
              : `${fmt(bd.data.returned)} ${rankPlural}.`}{" "}
            Click a group to go deeper, or a genus or species to open its dashboard.
          </p>
          <TileList items={items} sizeBy={sizeBy} lens={lens} qmap={qmap} onActivate={activate} />
        </>
      )}

      {hover && <TileTooltip hover={hover} />}
    </section>
  );
}

function LensButton({ lens, active, onClick }: { lens: Lens; active: boolean; onClick: () => void }) {
  return (
    <button type="button" className={"seg-btn" + (active ? " seg-btn--on" : "")} onClick={onClick} title={lens.legend}>
      {lens.label}
    </button>
  );
}

/** Keyboard and screen-reader path to the same content: the subgroups as a plain
 *  list, each with its numbers and links to go deeper or open its dashboard. */
function TileList({
  items, sizeBy, lens, qmap, onActivate,
}: {
  items: CladeSummary[];
  sizeBy: SizeBy;
  lens: Lens;
  qmap: Map<number, BucketStats>;
  onActivate: (n: CladeSummary) => void;
}) {
  const ranked = [...items]
    .filter((n) => sizeValue(n, sizeBy) > 0)
    .sort((a, b) => sizeValue(b, sizeBy) - sizeValue(a, sizeBy));
  const lensText = (n: CladeSummary): string => {
    const v = lens.value(n, qmap.get(n.taxid));
    if (v == null) return "no data";
    return lens.scale === "relative" ? (lens.fmt ?? fmt)(v) : `${fmtPct(v)}%`;
  };
  return (
    <details className="bmap-listwrap">
      <summary>View as a list</summary>
      <ol className="bmap-list">
        {ranked.map((n) => {
          const drillable = !!nextRank(n.rank);
          return (
            <li key={n.taxid} className="bmap-list__row">
              <button type="button" className="bmap-list__name" onClick={() => onActivate(n)}>
                {n.name}
              </button>
              <span className="bmap-list__rank">{n.rank}</span>
              <span className="bmap-list__meta">
                {fmt(n.n_rows)} species · {lens.legendLabel ?? lens.label} {lensText(n)}
              </span>
              <Link className="bmap-list__open" to={`/clade/${n.taxid}`}>
                {drillable ? "Open" : "Dashboard"}
              </Link>
            </li>
          );
        })}
      </ol>
    </details>
  );
}

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
      {node.composition.reference > 0 && <ValRow label="Reference genomes" value={fmt(node.composition.reference)} />}
    </div>
  );
}

function CovRow({ label, r }: { label: string; r: { covered: number; total: number; percent: number } }) {
  return (
    <div className="chart-tip__row">
      <span className="chart-tip__label">{label}</span>
      <span className="chart-tip__val">{r.total > 0 ? `${fmt(r.total)} · ${fmtPct(r.percent)}%` : "—"}</span>
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
