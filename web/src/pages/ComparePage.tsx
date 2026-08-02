import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { getCompare, getMetricsConfig, getQualityConfig } from "../api/queries";
import type { CompareGroup, MetricConfig, QualityStatConfig, TaxonRef } from "../api/types";
import RootPicker from "../components/RootPicker";
import { useAsync } from "../hooks/useAsync";
import { cladeLabel } from "../lib/clades";
import { fmt, fmtPct, fmtQuality } from "../lib/format";

const MAX_GROUPS = 6;
// Categorical series slots (see index.css --series-1..6, validated via the
// dataviz skill). Color follows the group entity, not its position, so removing
// one group never repaints the survivors.
const SERIES = ["--series-1", "--series-2", "--series-3", "--series-4", "--series-5", "--series-6"];

// A few one-click starting comparisons for the empty state (verified taxids).
const PRESETS: { label: string; taxids: number[] }[] = [
  { label: "Mammals vs Birds vs Fishes", taxids: [40674, 8782, 7898] },
  { label: "Insects vs Mammals", taxids: [50557, 40674] },
  { label: "Fungi vs Flowering plants", taxids: [4751, 3398] },
];

const displayName = (taxid: number, name?: string) => name ?? cladeLabel(taxid) ?? `TaxID ${taxid}`;

/** Round a percentage up to the next "nice" axis maximum (strictly greater, so
 *  the longest bar always leaves room for its value label at the tip). */
function niceCeil(x: number): number {
  for (const n of [1, 2, 5, 10, 20, 25, 50, 100]) if (x < n) return n;
  return 100;
}

/** Compare several groups' genomic-data coverage side by side. Groups live in the
 *  URL (`?taxids=a,b,c`), so a comparison is shareable and bookmarkable. */
export default function ComparePage() {
  const [params, setParams] = useSearchParams();
  const taxids = useMemo(
    () =>
      (params.get("taxids") ?? "")
        .split(",")
        .map((s) => Number(s.trim()))
        .filter((n) => Number.isInteger(n) && n > 0)
        .slice(0, MAX_GROUPS),
    [params],
  );
  const key = taxids.join(",");

  const [names, setNames] = useState<Record<number, string>>({});
  const setTaxids = (next: number[]) => {
    const p = new URLSearchParams(params);
    if (next.length) p.set("taxids", next.join(","));
    else p.delete("taxids");
    setParams(p);
  };
  const addGroup = (t: TaxonRef) => {
    if (taxids.includes(t.taxid) || taxids.length >= MAX_GROUPS) return;
    setNames((n) => ({ ...n, [t.taxid]: t.name }));
    setTaxids([...taxids, t.taxid]);
  };
  const removeGroup = (taxid: number) => setTaxids(taxids.filter((t) => t !== taxid));

  const metrics = useAsync(getMetricsConfig, []);
  const quality = useAsync(getQualityConfig, []);
  const data = useAsync(
    () => (taxids.length ? getCompare(taxids) : Promise.resolve({ groups: [] })),
    [key],
  );
  // Learn names from the response too (covers a fresh shared-link load).
  useEffect(() => {
    if (!data.data) return;
    setNames((n) => {
      const merged = { ...n };
      for (const g of data.data!.groups) merged[g.taxid] = g.name;
      return merged;
    });
  }, [data.data]);

  // Stable color slot per group: kept while the group is present, freed on remove.
  const slots = useRef<Map<number, number>>(new Map());
  const colorVar = useMemo(() => {
    const map = slots.current;
    for (const t of [...map.keys()]) if (!taxids.includes(t)) map.delete(t);
    const used = new Set(map.values());
    for (const t of taxids) {
      if (map.has(t)) continue;
      let s = 0;
      while (used.has(s)) s++;
      map.set(t, s);
      used.add(s);
    }
    return (taxid: number) => SERIES[(map.get(taxid) ?? 0) % SERIES.length];
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  const groups = data.data?.groups ?? [];

  return (
    <section className="cmp">
      <header className="cmp__head">
        <h1 className="cmp__title">Compare groups</h1>
        <p className="cmp__lede">
          Line up groups side by side to compare their genomic data coverage. Coverage is the share
          of species with data, so groups of very different sizes compare fairly.
        </p>
      </header>

      <div className="cmp__controls">
        <div className="cmp__add">
          <RootPicker
            onPick={addGroup}
            placeholder={
              taxids.length >= MAX_GROUPS
                ? `Up to ${MAX_GROUPS} groups`
                : "Add a group by name or TaxID"
            }
          />
        </div>
        {taxids.length > 0 && (
          <ul className="cmp__chips">
            {taxids.map((t) => (
              <li key={t} className="cmp__chip">
                <span className="cmp__swatch" style={{ background: `var(${colorVar(t)})` }} />
                <Link to={`/clade/${t}`} className="cmp__chip-name">
                  {displayName(t, names[t])}
                </Link>
                <button
                  type="button"
                  className="cmp__chip-x"
                  onClick={() => removeGroup(t)}
                  aria-label={`Remove ${displayName(t, names[t])}`}
                  title="Remove"
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {taxids.length === 0 && (
        <div className="cmp__empty">
          <p>Add two or more groups to compare, or start with:</p>
          <div className="cmp__presets">
            {PRESETS.map((p) => (
              <button
                key={p.label}
                type="button"
                className="cmp__preset"
                onClick={() => setTaxids(p.taxids)}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {data.error && <p className="notice notice--error">{data.error}</p>}
      {taxids.length > 0 && data.loading && !data.data && <p className="cmp__status">Loading…</p>}

      {groups.length > 0 && metrics.data && (
        <CompareChart groups={groups} metrics={metrics.data} colorVar={colorVar} names={names} />
      )}
      {groups.length > 0 && metrics.data && quality.data && (
        <CompareTable
          groups={groups}
          metrics={metrics.data}
          quality={quality.data}
          colorVar={colorVar}
          names={names}
        />
      )}
    </section>
  );
}

// --- Grouped bar chart: coverage % by resource, one color per group ----------
function CompareChart({
  groups,
  metrics,
  colorVar,
  names,
}: {
  groups: CompareGroup[];
  metrics: MetricConfig[];
  colorVar: (taxid: number) => string;
  names: Record<number, string>;
}) {
  const maxPct = Math.max(
    1,
    ...groups.flatMap((g) => metrics.map((m) => g.resources[m.key]?.percent ?? 0)),
  );
  const axisMax = niceCeil(maxPct);
  const ticks = [0, 0.25, 0.5, 0.75, 1];

  return (
    <figure className="ccht">
      <figcaption className="ccht__cap">Coverage: share of species with data</figcaption>
      <ul className="ccht__legend">
        {groups.map((g) => (
          <li key={g.taxid} className="ccht__legend-item">
            <span className="ccht__swatch" style={{ background: `var(${colorVar(g.taxid)})` }} />
            {displayName(g.taxid, names[g.taxid])}
          </li>
        ))}
      </ul>

      <div className="ccht__plot">
        <div className="ccht__grid" aria-hidden="true">
          {ticks.map((t) => (
            <span key={t} className="ccht__gridline" style={{ left: `${t * 100}%` }} />
          ))}
        </div>

        {metrics.map((m) => (
          <div key={m.key} className="ccht__res">
            <div className="ccht__res-label">{m.card_title}</div>
            {groups.map((g) => {
              const r = g.resources[m.key];
              const pct = r?.percent ?? 0;
              return (
                <div
                  key={g.taxid}
                  className="ccht__barrow"
                  title={`${displayName(g.taxid, names[g.taxid])} · ${m.card_title}: ${fmtPct(
                    pct,
                  )}% (${fmt(r?.covered ?? 0)} of ${fmt(g.n_rows)} species)`}
                >
                  <div
                    className="ccht__bar"
                    style={{
                      width: `${Math.max((pct / axisMax) * 100, 0.6)}%`,
                      background: `var(${colorVar(g.taxid)})`,
                    }}
                  />
                  <span className="ccht__barval">{fmtPct(pct)}%</span>
                </div>
              );
            })}
          </div>
        ))}
      </div>

      <div className="ccht__axis" aria-hidden="true">
        {ticks.map((t) => (
          <span key={t} className="ccht__tick" style={{ left: `${t * 100}%` }}>
            {t === 0 ? "0" : `${fmtPct(axisMax * t)}%`}
          </span>
        ))}
      </div>
    </figure>
  );
}

// --- Numbers table: exact coverage + the quality dimension, sortable ---------
type SortState = { key: string; dir: "asc" | "desc" } | null;

function CompareTable({
  groups,
  metrics,
  quality,
  colorVar,
  names,
}: {
  groups: CompareGroup[];
  metrics: MetricConfig[];
  quality: QualityStatConfig[];
  colorVar: (taxid: number) => string;
  names: Record<number, string>;
}) {
  const [sort, setSort] = useState<SortState>(null);

  const qMap = (g: CompareGroup) => Object.fromEntries(g.quality.map((q) => [q.key, q.value]));
  // Numeric columns: species, each resource coverage %, each quality stat.
  const columns = [
    { key: "n_rows", label: "Species", get: (g: CompareGroup) => g.n_rows, fmt: (v: number) => fmt(v) },
    ...metrics.map((m) => ({
      key: `r_${m.key}`,
      label: `${m.card_title} %`,
      get: (g: CompareGroup) => g.resources[m.key]?.percent ?? null,
      fmt: (v: number) => `${fmtPct(v)}%`,
    })),
    ...quality.map((q) => ({
      key: `q_${q.key}`,
      label: q.card_title,
      get: (g: CompareGroup) => qMap(g)[q.key] ?? null,
      fmt: (v: number) => fmtQuality(v, q.fmt),
    })),
  ];

  const sorted = useMemo(() => {
    if (!sort) return groups;
    const col = columns.find((c) => c.key === sort.key);
    if (!col) return groups;
    const dir = sort.dir === "asc" ? 1 : -1;
    return [...groups].sort((a, b) => {
      const va = col.get(a);
      const vb = col.get(b);
      if (va === null) return 1; // nulls last regardless of dir
      if (vb === null) return -1;
      return (va - vb) * dir;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groups, sort]);

  const onSort = (k: string) =>
    setSort((s) => (s?.key === k ? { key: k, dir: s.dir === "desc" ? "asc" : "desc" } : { key: k, dir: "desc" }));

  return (
    <div className="cmp-table-wrap">
      <table className="cmp-table">
        <thead>
          <tr>
            <th scope="col">Group</th>
            {columns.map((c) => (
              <th key={c.key} scope="col">
                <button type="button" className="cmp-table__sort" onClick={() => onSort(c.key)}>
                  {c.label}
                  <span className="cmp-table__arrow">
                    {sort?.key === c.key ? (sort.dir === "desc" ? " ▾" : " ▴") : ""}
                  </span>
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((g) => (
            <tr key={g.taxid}>
              <th scope="row" className="cmp-table__group">
                <span className="cmp__swatch" style={{ background: `var(${colorVar(g.taxid)})` }} />
                <Link to={`/clade/${g.taxid}`}>{displayName(g.taxid, names[g.taxid])}</Link>
              </th>
              {columns.map((c) => {
                const v = c.get(g);
                return (
                  <td key={c.key} className="cmp-table__num">
                    {v === null ? "—" : c.fmt(v)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
