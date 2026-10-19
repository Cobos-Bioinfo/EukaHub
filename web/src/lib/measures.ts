// What a chart's colour can show: always a share, so every measure uses the same
// colour ranges (lib/ranges.ts). The Data map and the Tree of Life offer these.
import type { CladeSummary } from "../api/types";
import { fmtPct } from "./format";

function levels(n: CladeSummary): { top: number; total: number } {
  const c = n.composition;
  return { top: c.complete + c.chromosome, total: c.complete + c.chromosome + c.scaffold + c.contig };
}
export function contiguityPct(n: CladeSummary): number | null {
  const { top, total } = levels(n);
  return total > 0 ? (top / total) * 100 : null;
}

/** One measure: the share it colours by, and words for it. `count` gives the
 *  share's parts for a list. */
export interface Measure {
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
  count: (n) => ({ part: n.resources[key]?.covered ?? 0, whole: n.species }),
});
export const MEASURES: Measure[] = [
  resource("assemblies", "Assemblies", "a genome assembly", "assembled", "With an assembly"),
  resource("annotations", "Annotations", "an annotation", "annotated", "With an annotation"),
  resource("rna_seq", "RNA-Seq (any)", "RNA-Seq runs", "with RNA-Seq", "With RNA-Seq"),
  resource("long_read_rna_seq", "Long-read RNA-Seq", "long-read RNA-Seq runs", "with long reads", "With long reads"),
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

/** The measure named in the address (`?colour=`), assemblies by default. */
export const measureOf = (key: string | null): Measure =>
  MEASURES.find((m) => m.key === key) ?? MEASURES[0];

/** A taxon's share as a phrase: "12.5% assembled", "None yet" or "No assemblies"
 *  (a share of assemblies with none to count). */
export function shareText(measure: Measure, n: CladeSummary): string {
  const share = measure.share(n);
  if (share === null) return "No assemblies";
  return share > 0 ? `${fmtPct(share)}% ${measure.word}` : "None yet";
}
