import { useLocation } from "react-router";

import { getTaxon, type TaxonWithLineage } from "../api/queries";
import { parseCladePath, type CladeView } from "../lib/clade";
import { useAsync } from "./useAsync";

/** For the app shell, which sits outside the clade routes: the clade and view the
 *  address shows (the clade once loaded), or null outside the clade pages. */
export function useCurrentClade(): {
  taxid: number;
  view: CladeView;
  clade?: TaxonWithLineage;
} | null {
  const route = parseCladePath(useLocation().pathname);
  const taxid = route?.taxid;
  const { data } = useAsync(() => (taxid ? getTaxon(taxid) : Promise.resolve(null)), [taxid]);
  return route && { ...route, clade: data ?? undefined };
}
