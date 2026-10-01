import { Fragment } from "react";
import { Link } from "react-router";

import type { TaxonRef } from "../api/types";
import { SPINE_TAXIDS } from "../lib/taxonomy";

/** The lineage from Eukaryota down to the current taxon (every NCBI rank),
 *  shown as a wrapping breadcrumb. */
export default function Breadcrumb({
  lineage,
  currentTaxid,
}: {
  lineage: TaxonRef[];
  currentTaxid: number;
}) {
  const hops = lineage.filter((t) => !SPINE_TAXIDS.has(t.taxid));

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
