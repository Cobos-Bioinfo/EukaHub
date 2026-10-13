import { Link } from "react-router";

import {
  getAbout,
  getAssemblies,
  getMetricsConfig,
  getQualityConfig,
  getTaxonStats,
} from "../api/queries";
import type { Taxon } from "../api/types";
import AboutCard from "../components/AboutCard";
import Classification from "../components/Classification";
import { TaxonError } from "../components/ErrorPage";
import GapsPointer from "../components/GapsPointer";
import MetricCard from "../components/MetricCard";
import NoDataNotice from "../components/NoDataNotice";
import QualitySection from "../components/QualitySection";
import RecommendedGenomes from "../components/RecommendedGenomes";
import SeeAlso from "../components/SeeAlso";
import SpeciesLinks from "../components/SpeciesLinks";
import SubspeciesSection from "../components/SubspeciesSection";
import { CompareIcon } from "../components/icons";
import { useAsync } from "../hooks/useAsync";
import { isUnit } from "../lib/clade";
import { fmt, fmtPct } from "../lib/format";
import { INFORMAL_SPECIES_RANK } from "../lib/taxonomy";
import { useClade } from "./CladeLayout";

/** The Summary view of one group: a sentence on how much of it has data, the
 *  coverage of each source, its recommended genomes, where the gaps are, the
 *  quality of its records, then its classification and Wikipedia's summary. The
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
    <section className="summary">
      <header className="summary__head">
        <div className="summary__id">
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
            !unit && !noData && <Headline clade={s} />
          )}
        </div>
        <Link className="dashboard__compare" to={`/compare?taxids=${taxid}`}>
          <CompareIcon size={15} />
          Add to compare
        </Link>
      </header>

      {noData ? (
        <>
          <NoDataNotice
            taxid={taxid}
            name={s.name}
            rank={s.rank}
            isUnit={unit}
            species={s.species}
            ncbiUrlTemplate={metrics.data.find((m) => m.key === "assemblies")?.external_url_template}
          />
          {unit && <SeeAlso clade={s} />}
        </>
      ) : (
        <>
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

          <div className="summary__row">
            {s.resources.assemblies.total > 0 && <RecommendedGenomes clade={s} />}
            {unit ? (
              <div className="summary__narrow">
                <SpeciesLinks metrics={metrics.data} taxid={taxid} />
              </div>
            ) : (
              <GapsPointer clade={s} />
            )}
          </div>

          {quality.data && (
            <QualitySection
              quality={quality.data}
              stats={stats.data?.stats}
              loading={stats.loading}
              error={stats.error}
              retry={stats.reload}
              assemblies={s.resources.assemblies.total}
              annotations={s.resources.annotations.total}
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
        </>
      )}

      <div className="summary__row">
        <Classification lineage={s.lineage} />
        {about.data && (
          <div className="summary__wide">
            <AboutCard about={about.data} />
          </div>
        )}
      </div>
    </section>
  );
}

/** "5,888 species. 1,130 of them (19.2%) have a genome assembly, and 579 have
 *  one that meets the EBP standard." */
function Headline({ clade }: { clade: Taxon }) {
  const { covered, percent } = clade.resources.assemblies;
  const ebp = useAsync(
    () =>
      covered > 0
        ? getAssemblies(clade.taxid, { ebp_standard: true, one_per_species: true, limit: 1 }).then(
            (p) => p.total,
          )
        : Promise.resolve(0),
    [clade.taxid],
  );
  const species = `${fmt(clade.species)} species`;
  if (covered === 0) {
    return <p className="summary__headline">{species}, none of them with a genome assembly yet.</p>;
  }
  const have = covered === 1 ? "has" : "have";
  return (
    <p className="summary__headline">
      {species}. {fmt(covered)} of them ({fmtPct(percent)}%) {have} a genome assembly
      {ebp.data
        ? `, and ${fmt(ebp.data)} ${ebp.data === 1 ? "has" : "have"} one that meets the EBP standard.`
        : "."}
    </p>
  );
}
