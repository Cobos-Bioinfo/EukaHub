// The current clade is the app's state: every view of one clade lives under
// /clade/:taxid, and moving between clades keeps the view.
import type { Taxon } from "../api/types";
import { INFORMAL_SPECIES_RANK } from "./taxonomy";

export type CladeView = "summary" | "map" | "records" | "tree" | "gaps";

export const VIEWS: { view: CladeView; label: string; path: string }[] = [
  { view: "summary", label: "Summary", path: "" },
  { view: "map", label: "Data map", path: "/map" },
  { view: "records", label: "Records", path: "/records" },
  { view: "tree", label: "Tree of Life", path: "/tree" },
  { view: "gaps", label: "Gaps", path: "/gaps" },
];

export function cladePath(taxid: number, view: CladeView = "summary"): string {
  return `/clade/${taxid}${VIEWS.find((v) => v.view === view)?.path ?? ""}`;
}

/** The clade and view an address shows, or null outside the clade pages. */
export function parseCladePath(pathname: string): { taxid: number; view: CladeView } | null {
  const m = pathname.match(/^\/clade\/(\d+)(?:\/(map|records|tree|gaps))?\/?$/);
  return m ? { taxid: Number(m[1]), view: (m[2] as CladeView | undefined) ?? "summary" } : null;
}

/** A species, an informal species or a finer taxon: one unit, with no breakdown below it. */
export function isUnit(t: Pick<Taxon, "rank" | "is_infraspecific">): boolean {
  return t.is_infraspecific || t.rank === "species" || t.rank === INFORMAL_SPECIES_RANK;
}

export function hasRecords(t: Pick<Taxon, "resources">): boolean {
  return t.resources.ass.total > 0 || t.resources.ann.total > 0;
}

/** The views a clade offers: a unit has no Data map or Gaps, and Records shows
 *  only when there are records to list. */
export function viewsOf(t: Taxon): CladeView[] {
  return VIEWS.map((v) => v.view).filter(
    (v) => !((v === "map" || v === "gaps") && isUnit(t)) && !(v === "records" && !hasRecords(t)),
  );
}

/** `view` if `t` offers it, else its Summary. */
export function viewFor(t: Taxon, view: CladeView): CladeView {
  return viewsOf(t).includes(view) ? view : "summary";
}
