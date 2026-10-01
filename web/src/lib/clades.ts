import type { CladeGroup } from "../api/types";

/** A random curated group's taxid, never the one the user is already looking at. */
export function pickRandomTaxid(groups: CladeGroup[], exclude?: number): number | undefined {
  const pool = groups.filter((g) => g.taxid !== exclude);
  const list = pool.length > 0 ? pool : groups;
  return list.length > 0 ? list[Math.floor(Math.random() * list.length)].taxid : undefined;
}
