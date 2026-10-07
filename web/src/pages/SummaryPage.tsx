import { Link } from "react-router";

import { getAbout, getMetricsConfig, getQualityConfig, getTaxonStats } from "../api/queries";
import AboutCard from "../components/AboutCard";
import { TaxonError } from "../components/ErrorPage";
import MetricCard from "../components/MetricCard";
import NoDataNotice from "../components/NoDataNotice";
import QualitySection from "../components/QualitySection";
import SpeciesLinks from "../components/SpeciesLinks";
import SubspeciesSection from "../components/SubspeciesSection";
import { CompareIcon } from "../components/icons";
import { useAsync } from "../hooks/useAsync";
import { cladePath, hasRecords, isUnit } from "../lib/clade";
import { fmt } from "../lib/format";
import { INFORMAL_SPECIES_RANK } from "../lib/taxonomy";
import { useClade } from "./CladeLayout";

/** The Summary view of one group: how much data it has and of what quality. The
 *  breakdown is on the Data map and the records on Records. */
export default function SummaryPage() {
  const s = useClade();
  const taxid = s.taxid;
  const stats = useAsync(() => getTaxonStats(taxid), [taxid]);
  const metrics = useAsync(() => getMetricsConfig(), []);
  const quality = useAsync(() => getQualityConfig(), []);
  // Decorative Wikipedia context: never gates the page, its error ignored.
  const about = useAsync(() => getAbout(s.name), [s.name]);

  if (metrics.error) {
    return <TaxonError taxid={String(taxid)} message={metrics.error} retry={metrics.reload} />;
  }
  if (!metrics.data) return <p className="notice">Loading…</p>;

  // A species, an informal species or a finer taxon is a single unit: its cards
  // count records (split into those on the taxon itself and on its finer taxa),
  // and its finer taxa are listed instead of a rank breakdown.
  const isInfra = s.is_infraspecific;
  const isInformal = s.rank === INFORMAL_SPECIES_RANK;
  const unit = isUnit(s);
  const noData = Object.values(s.resources).every((r) => r.total === 0);
  const rankWord = s.rank && s.rank !== "no rank" ? s.rank : "infraspecific taxon";
  const belowLabel = isInfra ? "from finer subdivisions" : "from subspecies and strains";

  return (
    <section className="dashboard">
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
              !unit && (
                <p className="dashboard__species">
                  <strong>{fmt(s.n_rows)}</strong> species in this clade
                </p>
              )
            )}
            <Link className="dashboard__compare" to={`/compare?taxids=${taxid}`}>
              <CompareIcon size={15} />
              Add to compare
            </Link>
          </header>
          {about.data && <AboutCard about={about.data} />}
          {unit && !noData && <SpeciesLinks metrics={metrics.data} taxid={taxid} />}
        </aside>

        <div className="dashboard__content">
          {noData ? (
            <NoDataNotice
              taxid={taxid}
              name={s.name}
              rank={s.rank}
              isUnit={unit}
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
                    mode={unit ? "count" : "coverage"}
                    direct={s.direct?.[m.key]}
                    belowLabel={belowLabel}
                  />
                ) : null;
              })}
            </div>
          )}

          {!noData && (hasRecords(s) || !unit) && (
            <ul className="dashboard__next">
              {hasRecords(s) && (
                <li>
                  {recordCounts(s.resources.ass.total, s.resources.ann.total)} listed on{" "}
                  <Link to={cladePath(taxid, "records")}>Records</Link>, with links to download
                  them.
                </li>
              )}
              {!unit && (
                <li>
                  See how this data is spread across the groups inside {s.name} on the{" "}
                  <Link to={cladePath(taxid, "map")}>Data map</Link>.
                </li>
              )}
            </ul>
          )}

          {quality.data && !noData && (
            <QualitySection
              quality={quality.data}
              stats={stats.data?.stats}
              loading={stats.loading}
              error={stats.error}
              retry={stats.reload}
              assemblies={s.resources.ass.total}
              annotations={s.resources.ann.total}
              composition={s.composition}
            />
          )}

          {unit && (
            <SubspeciesSection
              key={`subsp-${taxid}`}
              taxid={taxid}
              name={s.name}
              rank={s.rank}
              direct={s.direct}
              metrics={metrics.data}
            />
          )}
        </div>
      </div>
    </section>
  );
}

/** "5,665 assemblies and 2,343 annotations are", leaving out a count of zero. */
function recordCounts(assemblies: number, annotations: number): string {
  const parts = [
    assemblies > 0 && `${fmt(assemblies)} ${assemblies === 1 ? "assembly" : "assemblies"}`,
    annotations > 0 && `${fmt(annotations)} ${annotations === 1 ? "annotation" : "annotations"}`,
  ].filter(Boolean);
  return `${parts.join(" and ")} ${assemblies + annotations === 1 ? "is" : "are"}`;
}
