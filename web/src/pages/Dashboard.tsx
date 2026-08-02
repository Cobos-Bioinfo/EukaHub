import { Link, useParams } from "react-router-dom";

import {
  getAbout,
  getLineage,
  getMetricsConfig,
  getQualityConfig,
  getSummary,
} from "../api/queries";
import AboutCard from "../components/AboutCard";
import Breadcrumb from "../components/Breadcrumb";
import BreakdownMap from "../components/BreakdownMap";
import MetricCard from "../components/MetricCard";
import QualitySection from "../components/QualitySection";
import RecordBrowser from "../components/RecordBrowser";
import SpeciesLinks from "../components/SpeciesLinks";
import SubspeciesSection from "../components/SubspeciesSection";
import { TreeIcon } from "../components/icons";
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
  const quality = useAsync(() => getQualityConfig(), []);
  // Decorative Wikipedia context — never gates the page; rendered only if it
  // resolves to a summary, its error deliberately ignored.
  const about = useAsync(() => getAbout(taxid), [taxid]);

  if (!validId) return <p className="notice notice--error">Invalid taxon id.</p>;
  if (summary.error) return <p className="notice notice--error">{summary.error}</p>;
  if (summary.loading || metrics.loading || !summary.data || !metrics.data) {
    return <p className="notice">Loading…</p>;
  }

  const s = summary.data;
  // Below-species taxa (subspecies/strains/...) are leaf detail: show their own
  // record counts + source links, and list any finer taxa beneath them, but no
  // clade coverage summary or generic rank breakdown. A species is also a leaf
  // for these purposes (its "breakdown" is its subspecies).
  const isLeaf = s.is_infraspecific;
  const isSpecies = s.rank === "species";
  const showLinks = isSpecies || isLeaf;
  const showBreakdown = !isSpecies && !isLeaf;
  const showInfra = isSpecies || isLeaf;
  // Per-record drill-down only when the clade actually has assemblies or
  // annotations (avoids an empty browser + its fetches for data-less taxa).
  const hasRecords = s.resources.ass.total > 0 || s.resources.ann.total > 0;
  const rankWord = s.rank && s.rank !== "no rank" ? s.rank : "infraspecific taxon";

  return (
    <section className="dashboard">
      {lineage.data && <Breadcrumb lineage={lineage.data.lineage} currentTaxid={taxid} />}

      <div className="dashboard__body">
        <aside className="dashboard__side">
          <header className="dashboard__head">
            <div className="dashboard__title">
              <h1 className="dashboard__name">{s.name}</h1>
              <span className="rank-badge">{s.rank}</span>
            </div>
            {isLeaf ? (
              <p className="dashboard__note">
                This {rankWord} has its own data. It is not counted toward its parent species or any
                higher group. <Link to="/faq#subspecies">See FAQs</Link>
              </p>
            ) : (
              <p className="dashboard__species">
                <strong>{fmt(s.n_rows)}</strong> species in this clade
              </p>
            )}
          </header>
          {about.data && <AboutCard about={about.data} />}
          {!isLeaf && (
            <Link className="dashboard__tree-link" to={`/tree/${taxid}`}>
              <TreeIcon size={17} />
              Explore <em>this group</em> in the Tree of Life →
            </Link>
          )}
          {showLinks && <SpeciesLinks metrics={metrics.data} taxid={taxid} />}
        </aside>

        <div className="dashboard__content">
          <div className="card-grid">
            {metrics.data.map((m) => {
              const value = s.resources[m.key];
              return value ? (
                <MetricCard
                  key={m.key}
                  config={m}
                  value={value}
                  taxid={taxid}
                  mode={isLeaf ? "count" : "coverage"}
                />
              ) : null;
            })}
          </div>

          {quality.data && (
            <QualitySection taxid={taxid} quality={quality.data} composition={s.composition} />
          )}

          {showBreakdown && (
            <BreakdownMap
              key={taxid}
              root={{ taxid, name: s.name, rank: s.rank }}
              rootLineage={lineage.data?.lineage}
              heading="Breakdown"
              variant="embed"
            />
          )}
          {showInfra && (
            <SubspeciesSection key={taxid} taxid={taxid} rank={s.rank} metrics={metrics.data} />
          )}
          {hasRecords && <RecordBrowser key={taxid} taxid={taxid} />}
        </div>
      </div>
    </section>
  );
}
