// The ranks a group is broken down by (the Data map, the Summary's gaps).
import type { TargetRank, TaxonRef } from "../api/types";

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
export function nextRank(rank: string): TargetRank | null {
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
export function targetRankFor(focus: TaxonRef, lineage: string[]): TargetRank | null {
  if (LADDER.includes(focus.rank)) return nextRank(focus.rank);
  for (let i = lineage.length - 1; i >= 0; i--) {
    if (LADDER.includes(lineage[i])) return nextRank(lineage[i]);
  }
  return nextRank(focus.rank); // no canonical ancestor → phylum via the -1 path
}
/** Every rank the focus can be broken down by, coarse to fine. */
export function ranksBelow(first: TargetRank | null): TargetRank[] {
  return first ? ALLOWED.slice(ALLOWED.indexOf(first)) : [];
}
export const RANK_PLURAL: Record<string, string> = {
  phylum: "phyla", class: "classes", order: "orders",
  family: "families", genus: "genera", species: "species",
};
