import { Link, useParams } from "react-router-dom";

import { getAbout, getLineage, getMetricsConfig, getSummary } from "../api/queries";
import AboutCard from "../components/AboutCard";
import Breadcrumb from "../components/Breadcrumb";
import BreakdownSection from "../components/BreakdownSection";
import MetricCard from "../components/MetricCard";
import { useAsync } from "../hooks/useAsync";
import { fmt } from "../lib/format";

/** The Genomic Resource Summary (Q1) for one taxon. */
export default function Dashboard() {
  const { taxid: taxidParam } = useParams();
  const taxid = Number(taxidParam);
  const validId = Number.isInteger(taxid) && taxid > 0;

  const summary = useAsync(() => getSummary(taxid), [taxid]);
  const lineage = useAsync(() => getLineage(taxid), [taxid]);
  const metrics = useAsync(() => getMetricsConfig(), []);
  // Decorative Wikipedia context — never gates the page; rendered only if it
  // resolves to a summary, its error deliberately ignored.
  const about = useAsync(() => getAbout(taxid), [taxid]);

  if (!validId) return <p className="notice notice--error">Invalid taxon id.</p>;
  if (summary.error) return <p className="notice notice--error">{summary.error}</p>;
  if (summary.loading || metrics.loading || !summary.data || !metrics.data) {
    return <p className="notice">Loading…</p>;
  }

  const s = summary.data;
  return (
    <section className="dashboard">
      {lineage.data && <Breadcrumb lineage={lineage.data.lineage} currentTaxid={taxid} />}

      <header className="dashboard__head">
        <div className="dashboard__title">
          <h1 className="dashboard__name">{s.name}</h1>
          <span className="rank-badge">{s.rank}</span>
        </div>
        <p className="dashboard__species">
          <strong>{fmt(s.n_rows)}</strong> species in this clade
        </p>
      </header>

      <div className="dashboard__body">
        <aside className="dashboard__side">
          {about.data && <AboutCard about={about.data} />}
          <Link className="dashboard__tree-link" to={`/tree/${taxid}`}>
            🌳 Explore <em>this clade</em> in the Tree of Life →
          </Link>
        </aside>

        <div className="dashboard__content">
          <div className="card-grid">
            {metrics.data.map((m) => {
              const value = s.resources[m.key];
              return value ? (
                <MetricCard key={m.key} config={m} value={value} taxid={taxid} />
              ) : null;
            })}
          </div>

          <BreakdownSection
            key={taxid}
            taxid={taxid}
            rootName={s.name}
            rootRank={s.rank}
            metrics={metrics.data}
          />
        </div>
      </div>
    </section>
  );
}
