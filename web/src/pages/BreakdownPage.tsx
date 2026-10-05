import { useParams } from "react-router";

import { getLineage } from "../api/queries";
import BreakdownMap from "../components/BreakdownMap";
import { TaxonError } from "../components/ErrorPage";
import ViewSwitcher from "../components/ViewSwitcher";
import { useAsync } from "../hooks/useAsync";

/** Full-screen home for the data map. Resolves the route taxon's name + rank
 *  (to seed the map without a redundant fetch inside the component) and renders
 *  the map tall. Drilling stays in-component; the breadcrumb walks back. */
export default function BreakdownPage() {
  const { taxid: taxidParam } = useParams();
  const id = Number(taxidParam);
  const lineage = useAsync(() => getLineage(id), [id]);

  if (!Number.isInteger(id) || id <= 0)
    return <TaxonError taxid={taxidParam} />;
  if (lineage.error) {
    return (
      <TaxonError
        taxid={taxidParam}
        status={lineage.status}
        message={lineage.error}
        retry={lineage.reload}
      />
    );
  }
  if (!lineage.data) return <p className="notice">Loading…</p>;

  const root = { taxid: lineage.data.taxid, name: lineage.data.name, rank: lineage.data.rank };
  return (
    <section className="bmap-page">
      <ViewSwitcher taxid={root.taxid} name={root.name} current="map" layout="row" />
      <BreakdownMap
        root={root}
        rootLineage={lineage.data.lineage}
        heading="Where's the data?"
        variant="page"
      />
    </section>
  );
}
