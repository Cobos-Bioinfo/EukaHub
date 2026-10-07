import { hierarchy, treemap, treemapResquarify } from "d3-hierarchy";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { exportTsvUrl, getBreakdown, getBreakdownQuality } from "../api/queries";
import type { CladeSummary, TargetRank, TaxonRef } from "../api/types";
import { useAsync } from "../hooks/useAsync";
import { cladePath } from "../lib/clade";
import { fmt, fmtBp, fmtPct } from "../lib/format";
import { RANGE_LABELS, rangeOf, rangeStyle } from "../lib/ranges";
import RangeLegend from "./RangeLegend";

// Drilling jumps to the next meaningful rank, not the immediate adjacency child.
// Taxonomy hides the interesting split several rankless clades deep (Mammalia
// holds one child, Theria, that carries almost every species), so a map of
// immediate children would be one giant tile. Jumping to the next canonical rank
// keeps every level a real comparison.
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
// we take the next canonical rank below it. Many taxa are rankless (rank "clade"
// or "no rank": Eutheria, Bilateria, Opisthokonta, ...), and for those
// nextRank("clade") would fall through to phylum, wrong for a clade that sits
// below phylum (Eutheria is under class Mammalia and has only orders below it).
// So for a rankless focus we anchor to the deepest canonical-ranked ancestor in
// its lineage and step down from there. `lineage` is the focus's root→node chain
// (inclusive).
function targetRankFor(focus: TaxonRef, lineage: string[]): TargetRank | null {
  if (LADDER.includes(focus.rank)) return nextRank(focus.rank);
  for (let i = lineage.length - 1; i >= 0; i--) {
    if (LADDER.includes(lineage[i])) return nextRank(lineage[i]);
  }
  return nextRank(focus.rank); // no canonical ancestor → phylum via the -1 path
}
/** Every rank the focus can be broken down by, coarse to fine. */
function ranksBelow(first: TargetRank | null): TargetRank[] {
  return first ? ALLOWED.slice(ALLOWED.indexOf(first)) : [];
}
const RANK_PLURAL: Record<string, string> = {
  phylum: "phyla", class: "classes", order: "orders",
  family: "families", genus: "genera", species: "species",
};
const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

type BucketStats = Record<string, number | null>;

function levels(n: CladeSummary): { top: number; total: number } {
  const c = n.composition;
  return { top: c.complete + c.chromosome, total: c.complete + c.chromosome + c.scaffold + c.contig };
}
function contiguityPct(n: CladeSummary): number | null {
  const { top, total } = levels(n);
  return total > 0 ? (top / total) * 100 : null;
}

/** What a tile's colour shows: always a share, so every measure uses the same
 *  colour ranges. `count` gives the share's parts for the list. */
interface Measure {
  key: string;
  label: string;
  legend: string;
  word: string;
  whole: string;
  part: string;
  share: (n: CladeSummary) => number | null;
  count: (n: CladeSummary) => { part: number; whole: number };
}
const resource = (key: string, label: string, what: string, word: string, part: string): Measure => ({
  key,
  label,
  legend: `Share of species with ${what}`,
  word,
  whole: "Species",
  part,
  share: (n) => ((n.resources[key]?.covered ?? 0) > 0 ? n.resources[key].percent : 0),
  count: (n) => ({ part: n.resources[key]?.covered ?? 0, whole: n.n_rows }),
});
const MEASURES: Measure[] = [
  resource("ass", "Assemblies", "a genome assembly", "assembled", "With an assembly"),
  resource("ann", "Annotations", "an annotation", "annotated", "With an annotation"),
  resource("rna", "RNA-Seq (any)", "RNA-Seq runs", "with RNA-Seq", "With RNA-Seq"),
  resource("lng", "Long-read RNA-Seq", "long-read RNA-Seq runs", "with long reads", "With long reads"),
  {
    key: "chrom",
    label: "Chromosome-level assemblies",
    legend: "Share of assemblies at chromosome level or better",
    word: "at chromosome level",
    whole: "Assemblies",
    part: "Chromosome level or better",
    share: contiguityPct,
    count: (n) => {
      const { top, total } = levels(n);
      return { part: top, whole: total };
    },
  },
];

type SizeBy = "species" | "assemblies";
const sizeValue = (n: CladeSummary, by: SizeBy): number =>
  Math.max(0, by === "species" ? n.n_rows : n.resources.ass.total);

// Groups under 1% of the total size share one tile, when there are at least three:
// their own tiles would be too small to label or to hit.
const SMALL_SHARE = 0.01;
const MIN_GROUPED = 3;

/** One tile standing for several small groups: their counts added up. */
function combine(members: CladeSummary[], name: string): CladeSummary {
  const sum = (f: (m: CladeSummary) => number) => members.reduce((a, m) => a + f(m), 0);
  const n_rows = sum((m) => m.n_rows);
  const resources = Object.fromEntries(
    Object.keys(members[0].resources).map((k) => {
      const covered = sum((m) => m.resources[k]?.covered ?? 0);
      const total = sum((m) => m.resources[k]?.total ?? 0);
      return [k, { covered, total, percent: n_rows > 0 ? (covered / n_rows) * 100 : 0 }];
    }),
  );
  const composition = {
    complete: sum((m) => m.composition.complete),
    chromosome: sum((m) => m.composition.chromosome),
    scaffold: sum((m) => m.composition.scaffold),
    contig: sum((m) => m.composition.contig),
    reference: sum((m) => m.composition.reference),
  };
  return { taxid: -1, name, rank: "", n_rows, resources, composition, is_infraspecific: false };
}

interface Tile {
  node: CladeSummary;
  grouped: boolean;
  x0: number; y0: number; x1: number; y1: number;
  range: number;
}
interface Hover {
  node: CladeSummary;
  q?: BucketStats;
  x: number;
  y: number;
}

/** The current group's breakdown by a rank below it, as a map or a list. On the
 *  map each tile is a subgroup, sized by its species (or assemblies) and coloured
 *  by the range its share falls in, so a big pale tile is a large group with
 *  little data. Clicking a tile makes it the current group and stays on the Data
 *  map. The view, measure, size and rank live in the address (`?view=`,
 *  `?colour=`, `?size=`, `?rank=`), so a link keeps them and they survive a drill
 *  (all but the rank, which steps down with the group). */
export default function BreakdownMap({
  root,
  rootLineage,
}: {
  root: TaxonRef;
  /** The root's root→node lineage (inclusive), used to pick the breakdown rank
   *  when the root is rankless. */
  rootLineage: TaxonRef[];
}) {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const view = params.get("view") === "list" ? "list" : "map";
  const measure = MEASURES.find((m) => m.key === params.get("colour")) ?? MEASURES[0];
  const sizeBy: SizeBy = params.get("size") === "assemblies" ? "assemblies" : "species";
  const choose = (key: string, value: string, initial: string) =>
    setParams(
      (p) => {
        const q = new URLSearchParams(p);
        if (value === initial) q.delete(key);
        else q.set(key, value);
        return q;
      },
      { replace: true },
    );
  const [hover, setHover] = useState<Hover | null>(null);

  const focus = root;
  const rootRanks = useMemo(() => rootLineage.map((t) => t.rank), [rootLineage]);
  const firstRank = targetRankFor(focus, rootRanks);
  const rankOptions = ranksBelow(firstRank);
  const asked = params.get("rank") as TargetRank | null;
  const targetRank = asked && rankOptions.includes(asked) ? asked : firstRank;

  const query = targetRank && { rank: targetRank, sort: "n_rows" as const, exclude_empty: false, limit: 250 };
  const bd = useAsync(
    () => (query ? getBreakdown(focus.taxid, query) : Promise.resolve(null)),
    [focus.taxid, targetRank],
  );
  const quality = useAsync(
    () => (query ? getBreakdownQuality(focus.taxid, query) : Promise.resolve(null)),
    [focus.taxid, targetRank],
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
  }, [view]);

  const items = useMemo(() => bd.data?.items ?? [], [bd.data]);
  const rankNoun = targetRank ?? "group";
  const rankPlural = targetRank ? (RANK_PLURAL[targetRank] ?? `${targetRank}s`) : "subgroups";

  const { tiles, smallCount } = useMemo(() => {
    const sized = items.filter((n) => sizeValue(n, sizeBy) > 0);
    if (sized.length === 0) return { tiles: [] as Tile[], smallCount: 0 };
    const total = sized.reduce((a, n) => a + sizeValue(n, sizeBy), 0);
    const small = sized.filter((n) => sizeValue(n, sizeBy) < total * SMALL_SHARE);
    const grouped = small.length >= MIN_GROUPED;
    const shown = grouped ? sized.filter((n) => !small.includes(n)) : sized;
    const nodes = grouped ? [...shown, combine(small, `${small.length} smaller ${rankPlural}`)] : shown;

    type Datum = { children?: CladeSummary[] } & Partial<CladeSummary>;
    const tree = hierarchy<Datum>({ children: nodes } as Datum)
      .sum((d) => (Array.isArray(d.children) ? 0 : sizeValue(d as CladeSummary, sizeBy)))
      .sort((a, b) => (b.value ?? 0) - (a.value ?? 0));
    const laidOut = treemap<Datum>()
      .tile(treemapResquarify)
      .size([size.w, size.h])
      .paddingInner(3)
      .round(true)(tree);
    const tiles = laidOut.leaves().map((l) => {
      const node = l.data as CladeSummary;
      return {
        node,
        grouped: node.taxid === -1,
        x0: l.x0 ?? 0, y0: l.y0 ?? 0, x1: l.x1 ?? 0, y1: l.y1 ?? 0,
        range: rangeOf(measure.share(node)),
      };
    });
    return { tiles, smallCount: grouped ? small.length : 0 };
  }, [items, sizeBy, size.w, size.h, measure, rankPlural]);

  // Drilling keeps the view and the measure; the rank steps down with the group.
  const openOnMap = (taxid: number) => {
    const next = new URLSearchParams(params);
    next.delete("rank");
    const search = next.toString();
    return cladePath(taxid, "map") + (search ? `?${search}` : "");
  };
  const target = (n: CladeSummary) => (nextRank(n.rank) ? openOnMap(n.taxid) : cladePath(n.taxid));
  const shareText = (n: CladeSummary) => {
    const share = measure.share(n);
    if (share === null) return "No assemblies";
    return share > 0 ? `${fmtPct(share)}% ${measure.word}` : "None yet";
  };
  const capped = bd.data ? bd.data.total_matches > bd.data.returned : false;

  return (
    <section className="bmap-block bmap-block--page">
      <header className="bmap-block__head">
        <h1 className="bmap-block__title">
          {targetRank ? `${focus.name} by ${rankNoun}` : focus.name}
        </h1>
        {targetRank && (
          <p className="bmap-block__sub">
            Each tile is {/^[aeiou]/.test(rankNoun) ? "an" : "a"} {rankNoun}, sized by its number of{" "}
            {sizeBy}. The colour shows the {measure.legend.toLowerCase()}, so the big pale tiles
            are the gaps: large groups with little data.
          </p>
        )}
      </header>

      {targetRank && (
        <div className="bmap-controls">
          <div className="tree-controls__seg" role="group" aria-label="View">
            {(["map", "list"] as const).map((v) => (
              <button
                key={v}
                type="button"
                className={"seg-btn" + (v === view ? " seg-btn--on" : "")}
                aria-pressed={v === view}
                onClick={() => choose("view", v, "map")}
              >
                {v === "map" ? "Map" : "List"}
              </button>
            ))}
          </div>
          <label className="control">
            <span className="control__label">Colour by</span>
            <select
              className="control__select"
              value={measure.key}
              onChange={(e) => choose("colour", e.target.value, "ass")}
            >
              {MEASURES.map((m) => (
                <option key={m.key} value={m.key}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
          {rankOptions.length > 1 && (
            <label className="control">
              <span className="control__label">Show</span>
              <select
                className="control__select"
                value={targetRank}
                onChange={(e) => choose("rank", e.target.value, firstRank ?? "")}
              >
                {rankOptions.map((r) => (
                  <option key={r} value={r}>
                    {capitalize(RANK_PLURAL[r] ?? r)}
                  </option>
                ))}
              </select>
            </label>
          )}
          {view === "map" ? (
            <div className="control">
              <span className="control__label" id="bmap-size">
                Size by
              </span>
              <div className="tree-controls__seg" role="group" aria-labelledby="bmap-size">
                {(["species", "assemblies"] as SizeBy[]).map((s) => (
                  <button
                    key={s}
                    type="button"
                    className={"seg-btn" + (s === sizeBy ? " seg-btn--on" : "")}
                    aria-pressed={s === sizeBy}
                    onClick={() => choose("size", s, "species")}
                  >
                    {s === "species" ? "Species" : "Assemblies"}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <a className="dl bmap-controls__end" href={exportTsvUrl(focus.taxid, { rank: targetRank })}>
              Download this table (TSV)
            </a>
          )}
        </div>
      )}

      {targetRank && <RangeLegend title={measure.legend} />}

      {view === "map" ? (
        <div className="bmap bmap--page" ref={boxRef}>
          {bd.loading ? (
            <p className="notice">Mapping…</p>
          ) : bd.error ? (
            <p className="notice notice--error">{bd.error}</p>
          ) : !targetRank ? (
            <p className="notice">
              {focus.name} is a {focus.rank}, the finest rank shown here. Its records are on{" "}
              <Link to={cladePath(focus.taxid, "records")}>Records</Link>.
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
              const full = w >= 104 && h >= 64;
              const n = t.node;
              const action = t.grouped
                ? "Show them in the list."
                : nextRank(n.rank)
                  ? "Open it on the Data map."
                  : "Open its summary.";
              return (
                <button
                  key={n.taxid}
                  type="button"
                  className={"bmap-tile" + (t.grouped ? " bmap-tile--grouped" : "")}
                  style={{ left: t.x0, top: t.y0, width: w, height: h, ...rangeStyle(t.range) }}
                  onClick={() => (t.grouped ? choose("view", "list", "map") : navigate(target(n)))}
                  onMouseMove={(e) => setHover({ node: n, q: qmap.get(n.taxid), x: e.clientX, y: e.clientY })}
                  onMouseLeave={() => setHover(null)}
                  aria-label={`${n.name}, ${fmt(n.n_rows)} species, ${shareText(n)}. ${action}`}
                >
                  {labelled && (
                    <span className="bmap-tile__body">
                      <span className="bmap-tile__name">{n.name}</span>
                      {full && (
                        <>
                          <span className="bmap-tile__stat">
                            {sizeBy === "species"
                              ? `${fmt(n.n_rows)} species`
                              : `${fmt(n.resources.ass.total)} assemblies`}
                          </span>
                          <span className="bmap-tile__share">{shareText(n)}</span>
                        </>
                      )}
                    </span>
                  )}
                </button>
              );
            })
          )}
        </div>
      ) : (
        targetRank && (
          <TileTable
            items={items}
            measure={measure}
            rank={rankNoun}
            name={focus.name}
            linkTo={target}
            loading={bd.loading}
            error={bd.error}
          />
        )
      )}

      {bd.data && targetRank && items.length > 0 && (
        <p className="bmap-foot">
          {capped
            ? `The ${fmt(bd.data.returned)} largest ${rankPlural} by species, of ${fmt(bd.data.total_matches)}.`
            : `${fmt(bd.data.returned)} ${rankPlural}.`}{" "}
          {view === "map" &&
            smallCount > 0 &&
            `The ${smallCount} smallest are grouped in one tile, which opens the list. `}
          {view === "map"
            ? "Click a tile to make it the current group; you stay on the Data map."
            : "Click a name to make it the current group."}
        </p>
      )}

      {hover && view === "map" && <TileTooltip hover={hover} />}
    </section>
  );
}

/** The List view, and the text alternative to the map: every subgroup with the
 *  share the colour shows and its range. */
function TileTable({
  items, measure, rank, name, linkTo, loading, error,
}: {
  items: CladeSummary[];
  measure: Measure;
  rank: string;
  name: string;
  linkTo: (n: CladeSummary) => string;
  loading: boolean;
  error?: string;
}) {
  if (loading) return <p className="notice">Loading…</p>;
  if (error) return <p className="notice notice--error">{error}</p>;
  const rows = [...items].sort((a, b) => b.n_rows - a.n_rows);
  return (
    <div className="bd__table-wrap">
      <table className="bd-table bmap-table">
        <caption className="sr-only">
          {name} by {rank}: {measure.legend.toLowerCase()}
        </caption>
        <thead>
          <tr>
            <th scope="col">{capitalize(rank)}</th>
            <th scope="col" className="bd-num">{measure.whole}</th>
            <th scope="col" className="bd-num">{measure.part}</th>
            <th scope="col">Range</th>
            <th scope="col" className="bd-num">Without</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((n) => {
            const { part, whole } = measure.count(n);
            const share = measure.share(n);
            const range = rangeOf(share);
            return (
              <tr key={n.taxid}>
                <td className="bd-name">
                  <Link to={linkTo(n)}>{n.name}</Link>
                </td>
                <td className="bd-num" data-label={measure.whole}>
                  {fmt(whole)}
                </td>
                <td className="bd-num" data-label={measure.part}>
                  {fmt(part)}
                  {share !== null && share > 0 && ` (${fmtPct(share)}%)`}
                </td>
                <td data-label="Range">
                  <span className="ranges__swatch" style={{ background: rangeStyle(range).background }} />
                  {RANGE_LABELS[range]}
                </td>
                <td className="bd-num" data-label="Without">
                  {fmt(whole - part)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
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
