import { Link, useParams } from "react-router";

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
import NoDataNotice from "../components/NoDataNotice";
import QualitySection from "../components/QualitySection";
import RecordBrowser from "../components/RecordBrowser";
import SpeciesLinks from "../components/SpeciesLinks";
import SubspeciesSection from "../components/SubspeciesSection";
import ViewSwitcher from "../components/ViewSwitcher";
import { useAsync } from "../hooks/useAsync";
import { fmt } from "../lib/format";
import { INFORMAL_SPECIES_RANK } from "../lib/taxonomy";

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
  // A species, an informal species or a finer taxon is a single unit: its cards
  // count records (split into those on the taxon itself and on its finer taxa),
  // and its finer taxa are listed instead of a rank breakdown.
  const isInfra = s.is_infraspecific;
  const isInformal = s.rank === INFORMAL_SPECIES_RANK;
  const isUnit = isInfra || isInformal || s.rank === "species";
  // Per-record drill-down only when the clade actually has assemblies or
  // annotations (avoids an empty browser + its fetches for data-less taxa).
  const hasRecords = s.resources.ass.total > 0 || s.resources.ann.total > 0;
  const noData = Object.values(s.resources).every((r) => r.total === 0);
  const rankWord = s.rank && s.rank !== "no rank" ? s.rank : "infraspecific taxon";
  const belowLabel = isInfra ? "from finer subdivisions" : "from subspecies and strains";

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
            {isInfra ? (
              <p className="dashboard__note">
                This {rankWord} is not counted as a separate species. Its data counts toward its
                species and every group above it. <Link to="/faq#subspecies">See FAQs</Link>
              </p>
            ) : isInformal ? (
              <p className="dashboard__note">
                NCBI records this taxon without a formal species name, so it is not counted as a
                species. Its data counts toward every group above it.{" "}
                <Link to="/faq#informal-species">See FAQs</Link>
              </p>
            ) : (
              !isUnit && (
                <p className="dashboard__species">
                  <strong>{fmt(s.n_rows)}</strong> species in this clade
                </p>
              )
            )}
          </header>
          {about.data && <AboutCard about={about.data} />}
          {!isUnit && <ViewSwitcher taxid={taxid} name={s.name} current="dashboard" />}
          {isUnit && !noData && <SpeciesLinks metrics={metrics.data} taxid={taxid} />}
        </aside>

        <div className="dashboard__content">
          {noData ? (
            <NoDataNotice
              taxid={taxid}
              name={s.name}
              rank={s.rank}
              isUnit={isUnit}
              species={s.n_rows}
              ncbiUrlTemplate={metrics.data.find((m) => m.key === "ass")?.external_url_template}
            />
          ) : (
            <div className="card-grid">
              {metrics.data.map((m) => {
                const value = s.resources[m.key];
                return value ? (
                  <MetricCard
                    key={m.key}
                    config={m}
                    value={value}
                    taxid={taxid}
                    mode={isUnit ? "count" : "coverage"}
                    direct={s.direct?.[m.key]}
                    belowLabel={belowLabel}
                  />
                ) : null;
              })}
            </div>
          )}

          {quality.data && !noData && (
            <QualitySection taxid={taxid} quality={quality.data} composition={s.composition} />
          )}

          {!isUnit && !noData && !lineage.loading && (
            <BreakdownMap
              key={`bmap-${taxid}`}
              root={{ taxid, name: s.name, rank: s.rank }}
              rootLineage={lineage.data?.lineage}
              heading="Breakdown"
              variant="embed"
            />
          )}
          {isUnit && (
            <SubspeciesSection
              key={`subsp-${taxid}`}
              taxid={taxid}
              name={s.name}
              rank={s.rank}
              direct={s.direct}
              metrics={metrics.data}
            />
          )}
          {hasRecords && <RecordBrowser key={`rec-${taxid}`} taxid={taxid} />}
        </div>
      </div>
    </section>
  );
}
