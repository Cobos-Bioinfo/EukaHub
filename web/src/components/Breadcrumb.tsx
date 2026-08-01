import { Fragment } from "react";
import { Link } from "react-router-dom";

import type { TaxonRef } from "../api/types";

// Trim the two synthetic roots NCBI puts above every lineage.
const HIDDEN_TAXIDS = new Set([1, 131567]); // root, cellular organisms

/** The lineage from Eukaryota down to the current taxon (every NCBI rank),
 *  shown as a wrapping breadcrumb. */
export default function Breadcrumb({
  lineage,
  currentTaxid,
}: {
  lineage: TaxonRef[];
  currentTaxid: number;
}) {
  const hops = lineage.filter((t) => !HIDDEN_TAXIDS.has(t.taxid));

  return (
    <nav className="breadcrumb" aria-label="Lineage">
      <span className="breadcrumb__label">Lineage (all ranks):</span>
      {hops.map((t, i) => (
        <Fragment key={t.taxid}>
          {i > 0 && (
            <span className="breadcrumb__sep" aria-hidden="true">
              ›
            </span>
          )}
          {t.taxid === currentTaxid ? (
            <span className="breadcrumb__current" aria-current="page">
              {t.name}
            </span>
          ) : (
            <Link to={`/clade/${t.taxid}`}>{t.name}</Link>
          )}
        </Fragment>
      ))}
    </nav>
  );
}
