import { Link } from "react-router-dom";

import type { TaxonRef } from "../api/types";
import { isCanonicalRank } from "../lib/format";

/** Root→node lineage, filtered to canonical ranks (plus the current taxon). */
export default function Breadcrumb({
  lineage,
  currentTaxid,
}: {
  lineage: TaxonRef[];
  currentTaxid: number;
}) {
  const hops = lineage.filter((t) => isCanonicalRank(t.rank) || t.taxid === currentTaxid);

  return (
    <nav className="breadcrumb" aria-label="Lineage">
      {hops.map((t, i) => (
        <span key={t.taxid} className="breadcrumb__item">
          {i > 0 && <span className="breadcrumb__sep" aria-hidden="true">›</span>}
          {t.taxid === currentTaxid ? (
            <span className="breadcrumb__current" aria-current="page">
              {t.name}
            </span>
          ) : (
            <Link to={`/clade/${t.taxid}`}>{t.name}</Link>
          )}
        </span>
      ))}
    </nav>
  );
}
