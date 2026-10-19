import { Navigate, Outlet, useLocation, useOutletContext, useParams } from "react-router";

import { getTaxon, type TaxonWithLineage } from "../api/queries";
import { TaxonError } from "../components/ErrorPage";
import { useAsync } from "../hooks/useAsync";
import { cladePath, parseCladePath } from "../lib/clade";

type CladeContext = { clade: TaxonWithLineage };

/** Every view of one clade (`/clade/:taxid/...`): loads the clade once, shows its
 *  error page if it can't, and hands it to the view below. An address with a taxid
 *  NCBI has merged into another moves to that one, keeping the view and options. */
export default function CladeLayout() {
  const { taxid: param } = useParams();
  const { pathname, search } = useLocation();
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
  if (clade.data.taxid !== taxid) {
    return <Navigate replace to={cladePath(clade.data.taxid, parseCladePath(pathname)?.view) + search} />;
  }
  return <Outlet context={{ clade: clade.data } satisfies CladeContext} />;
}

/** The clade the current view shows. */
export function useClade(): TaxonWithLineage {
  return useOutletContext<CladeContext>().clade;
}
