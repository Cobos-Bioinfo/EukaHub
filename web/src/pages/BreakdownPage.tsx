import { Link } from "react-router";

import BreakdownMap from "../components/BreakdownMap";
import { cladePath, hasRecords, isUnit } from "../lib/clade";
import { useClade } from "./CladeLayout";

/** The Data map view of one group: its breakdown by the next rank down. */
export default function BreakdownPage() {
  const clade = useClade();
  if (isUnit(clade)) return <NoBreakdown />;
  return (
    <section className="bmap-page">
      <BreakdownMap
        root={{ taxid: clade.taxid, name: clade.name, rank: clade.rank }}
        rootLineage={clade.lineage}
      />
    </section>
  );
}

/** What the Data map and Gaps say for a species or a finer taxon, which have no
 *  groups below them (reached from a link or a search that kept the view). */
export function NoBreakdown() {
  const clade = useClade();
  return (
    <section className="errpage">
      <h1 className="errpage__title">{clade.name}</h1>
      <p className="errpage__text">
        {clade.name} is a single species or a part of one, with no groups below it to compare.
        See its{" "}
        <Link to={cladePath(clade.taxid)}>Summary</Link>
        {hasRecords(clade) && (
          <>
            {" "}
            or its <Link to={cladePath(clade.taxid, "records")}>Records</Link>
          </>
        )}
        .
      </p>
    </section>
  );
}
