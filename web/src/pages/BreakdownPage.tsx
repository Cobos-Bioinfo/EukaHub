import { useParams } from "react-router-dom";

import { getLineage } from "../api/queries";
import BreakdownMap from "../components/BreakdownMap";
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
    return <p className="notice notice--error">Invalid taxon id.</p>;
  if (lineage.error) return <p className="notice notice--error">{lineage.error}</p>;
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
