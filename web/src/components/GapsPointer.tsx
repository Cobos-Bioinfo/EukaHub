import { Link } from "react-router";

import { getGaps } from "../api/queries";
import type { TaxonWithLineage } from "../api/queries";
import { useAsync } from "../hooks/useAsync";
import { cladePath } from "../lib/clade";
import { fmt } from "../lib/format";
import { RANK_PLURAL, targetRankFor } from "../lib/ranks";

const SHOWN = 3;

/** The subgroups with the most species still without an assembly, as a pointer
 *  to the Data map, where the whole breakdown is. Hidden for a genus, whose
 *  subgroups are single species, and when nothing is missing. */
export default function GapsPointer({ clade }: { clade: TaxonWithLineage }) {
  const rank = targetRankFor(
    clade,
    clade.lineage.map((t) => t.rank),
  );
  const show = rank !== null && rank !== "species";
  const gaps = useAsync(
    () =>
      show
        ? getGaps({ root: clade.taxid, rank, resource: "assemblies", limit: SHOWN, include_quality: false })
        : Promise.resolve(null),
    [clade.taxid, rank],
  );
  const items = gaps.data?.items.filter((g) => g.gap > 0) ?? [];
  if (!show || items.length === 0) return null;
  const plural = RANK_PLURAL[rank] ?? `${rank}s`;

  return (
    <section className="panel summary__narrow" aria-labelledby="gaps-title">
      <h2 className="panel__title" id="gaps-title">
        Where the gaps are
      </h2>
      <p className="panel__sub">
        {plural.charAt(0).toUpperCase() + plural.slice(1)} with the most species that have no
        assembly yet.
      </p>
      <ul className="sum-gaps">
        {items.map((g) => (
          <li key={g.taxid} className="sum-gaps__item">
            <div className="sum-gaps__line">
              <Link to={cladePath(g.taxid)}>{g.name}</Link>
              <span className="sum-gaps__count">
                {fmt(g.gap)} of {fmt(g.species)} missing
              </span>
            </div>
            <span className="sum-gaps__bar" aria-hidden="true">
              <span style={{ width: `${Math.max(g.percent, 0.5)}%` }} />
            </span>
          </li>
        ))}
      </ul>
      <p className="panel__sub">The dark part of each bar is the share with an assembly.</p>
      <Link to={cladePath(clade.taxid, "map")}>Open the Data map →</Link>
    </section>
  );
}
