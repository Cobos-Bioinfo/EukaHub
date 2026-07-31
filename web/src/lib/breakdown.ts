// Presentation helpers for the breakdown (Q2) view: rank/sort option lists
// derived from the metric config, plus the client-side "displayed rows" TSV.

import type { Breakdown, MetricConfig, SortColumn, TargetRank } from "../api/types";

// Ranks the breakdown can target, coarse → fine (mirrors the API's TargetRank).
export const TARGET_RANKS: TargetRank[] = [
  "phylum",
  "class",
  "order",
  "family",
  "genus",
  "species",
];

// Major-rank order, used only to pick a sensible *default* target rank for a
// root: the first target rank strictly finer than the root's own rank.
const RANK_ORDER = [
  "domain",
  "superkingdom",
  "kingdom",
  "phylum",
  "class",
  "order",
  "family",
  "genus",
  "species",
];

/** A default target rank for a root: the broadest rank finer than its own. */
export function defaultRank(rootRank: string): TargetRank {
  const i = RANK_ORDER.indexOf(rootRank);
  if (i < 0) return "phylum"; // unranked root (clade / no rank) → broadest cut
  const next = TARGET_RANKS.find((r) => RANK_ORDER.indexOf(r) > i);
  return next ?? "species"; // root at/below species → nothing finer to show
}

export interface SortOption {
  value: SortColumn;
  label: string;
}

/** Sort options: total species, then each metric's covered-count and total. */
export function sortOptions(metrics: MetricConfig[]): SortOption[] {
  const opts: SortOption[] = [{ value: "n_rows", label: "Total species" }];
  for (const m of metrics) {
    opts.push({ value: `c_${m.key}` as SortColumn, label: m.sort_count_label });
    opts.push({ value: `s_${m.key}` as SortColumn, label: m.sort_total_label });
  }
  return opts;
}

const tsvCell = (v: string | number): string => String(v).replace(/[\t\n\r]/g, " ");

/** The currently displayed rows as a TSV string (grouped: all covered counts,
 *  then all totals — the same layout as the server's full-breakdown export). */
export function displayedRowsTsv(data: Breakdown, metrics: MetricConfig[]): string {
  const header = [
    "taxon_id",
    "name",
    "total_species",
    ...metrics.map((m) => `${m.card_title} (species)`),
    ...metrics.map((m) => `${m.card_title} (total)`),
  ];
  const rows = data.items.map((item) =>
    [
      item.taxid,
      item.name,
      item.n_rows,
      ...metrics.map((m) => item.resources[m.key].covered),
      ...metrics.map((m) => item.resources[m.key].total),
    ]
      .map(tsvCell)
      .join("\t"),
  );
  return [header.join("\t"), ...rows].join("\n") + "\n";
}

/** Trigger a browser download of `text` as `filename`. */
export function downloadText(
  filename: string,
  text: string,
  mime = "text/tab-separated-values",
): void {
  const url = URL.createObjectURL(new Blob([text], { type: mime }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
