import { Link, useNavigate, useParams } from "react-router-dom";

import { getLineage, getMetricsConfig } from "../api/queries";
import Breadcrumb from "../components/Breadcrumb";
import RadialTree from "../components/RadialTree";
import TreeOutline from "../components/TreeOutline";
import { useAsync } from "../hooks/useAsync";
import { useTree } from "../hooks/useTree";

/** The interactive radial Tree of Life for one root clade (`/tree/:taxid`). */
export default function TreePage() {
  const { taxid: taxidParam } = useParams();
  const taxid = Number(taxidParam);
  const validId = Number.isInteger(taxid) && taxid > 0;
  const navigate = useNavigate();

  const metrics = useAsync(() => getMetricsConfig(), []);
  const lineage = useAsync(() => getLineage(taxid), [taxid]);
  const tree = useTree(taxid);

  if (!validId) return <p className="notice notice--error">Invalid taxon id.</p>;
  if (lineage.error) return <p className="notice notice--error">{lineage.error}</p>;
  if (tree.error) return <p className="notice notice--error">{tree.error}</p>;

  const lin = lineage.data?.lineage;
  const node = lin && lin.length > 0 ? lin[lin.length - 1] : undefined;

  return (
    <section className="tree-page">
      {lineage.data && <Breadcrumb lineage={lineage.data.lineage} currentTaxid={taxid} />}

      <header className="tree-page__head">
        <div>
          <h1 className="tree-page__title">
            Tree of Life{node ? <> — <em>{node.name}</em></> : null}
          </h1>
          <p className="tree-page__sub">
            Explore the eukaryotic tree outward from this clade. Node size ∝ species;
            colour by a resource of your choice. Click a node to expand it and see its
            details, then open its dashboard from there. Scroll or use the buttons to zoom;
            drag to pan.
          </p>
        </div>
        <Link className="tree-page__back" to={`/clade/${taxid}`}>
          ← Dashboard
        </Link>
      </header>

      {metrics.data ? (
        <RadialTree tree={tree} metrics={metrics.data} onOpen={(t) => navigate(`/clade/${t}`)} />
      ) : (
        <p className="notice">Loading…</p>
      )}

      <details className="tree-details">
        <summary>Text outline (accessible view)</summary>
        <TreeOutline tree={tree} />
      </details>
    </section>
  );
}
