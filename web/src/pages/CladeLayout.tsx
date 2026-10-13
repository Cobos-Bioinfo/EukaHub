import { Outlet, useOutletContext, useParams } from "react-router";

import { getTaxon, type TaxonWithLineage } from "../api/queries";
import { TaxonError } from "../components/ErrorPage";
import { useAsync } from "../hooks/useAsync";

type CladeContext = { clade: TaxonWithLineage };

/** Every view of one clade (`/clade/:taxid/...`): loads the clade once, shows its
 *  error page if it can't, and hands it to the view below. */
export default function CladeLayout() {
  const { taxid: param } = useParams();
  const taxid = Number(param);
  const valid = Number.isInteger(taxid) && taxid > 0;
  const clade = useAsync(() => (valid ? getTaxon(taxid) : Promise.resolve(null)), [taxid]);

  if (!valid) return <TaxonError taxid={param} />;
  if (clade.error) {
    return (
      <TaxonError taxid={param} status={clade.status} message={clade.error} retry={clade.reload} />
    );
  }
  if (!clade.data) return <p className="notice">Loading…</p>;
  return <Outlet context={{ clade: clade.data } satisfies CladeContext} />;
}

/** The clade the current view shows. */
export function useClade(): TaxonWithLineage {
  return useOutletContext<CladeContext>().clade;
}
