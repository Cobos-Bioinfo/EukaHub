import { Link } from "react-router-dom";

import { getOverview } from "../api/queries";
import type { FeaturedClade } from "../api/types";
import RandomCladeButton from "../components/RandomCladeButton";
import RootPicker from "../components/RootPicker";
import { RandomIcon, TreeIcon } from "../components/icons";
import { useAsync } from "../hooks/useAsync";
import { cladeLabel, HERO_CHIPS } from "../lib/clades";
import { fmt, fmtCompact, fmtPct } from "../lib/format";

// The whole surveyed tree: the default "explore everything" entry point.
const EUKARYOTA_TAXID = 2759;

/** The landing / hero page at `/`. Puts the EukaHub name front and centre, then
 *  gives a strong entry point: a prominent search, quick-jump chips, a
 *  random-clade button for undecided visitors, and the two primary journeys
 *  (dashboard + Tree of Life). Below the hero, a live "at a glance" strip and a
 *  row of featured-group coverage cards give a sense of scale and of the gaps. */
export default function Landing() {
  return (
    <section className="hero">
      <h1 className="hero__wordmark">
        Euka<span>Hub</span>
      </h1>
      <p className="hero__tagline">Genomic data across the eukaryotic tree of life</p>
      <p className="hero__lede">
        See how much public genomic data exists for any group, and how it is spread across the
        tree of life beneath it.
      </p>

      <div className="hero__search">
        <RootPicker />
      </div>

      <div className="hero__chips">
        <span className="hero__chips-label">Try:</span>
        {HERO_CHIPS.map((c) => (
          <Link key={c.taxid} to={`/clade/${c.taxid}`} className="hero__chip">
            {c.label}
          </Link>
        ))}
      </div>

      <RandomCladeButton className="hero__surprise" title="Jump to a random group">
        <RandomIcon size={17} />
        Surprise me with a random clade
      </RandomCladeButton>

      <div className="hero__cta">
        <Link to={`/clade/${EUKARYOTA_TAXID}`} className="hero__btn hero__btn--primary">
          Explore Eukaryota →
        </Link>
        <Link to={`/tree/${EUKARYOTA_TAXID}`} className="hero__btn hero__btn--ghost">
          <TreeIcon size={17} />
          Tree of Life
        </Link>
      </div>

      <LandingOverview />
    </section>
  );
}

/** The live "at a glance" totals strip + featured-group cards. Fetched
 *  non-blocking: the hero renders instantly, and this whole block simply stays
 *  absent while loading or if the request fails (decorative, never load-bearing). */
function LandingOverview() {
  const { data } = useAsync(getOverview, []);
  if (!data) {
    return (
      <p className="hero__meta">Data from NCBI, Annotrieve, and ENA, across the eukaryotic tree.</p>
    );
  }
  const t = data.totals;
  const stats: { value: number; label: string }[] = [
    { value: t.species, label: "Eukaryotic species" },
    { value: t.assemblies, label: "Genome assemblies" },
    { value: t.annotations, label: "Annotated genomes" },
    { value: t.rna_seq, label: "RNA-Seq runs" },
  ];

  return (
    <div className="glance">
      <dl className="glance__grid" aria-label="Public data at a glance">
        {stats.map((s) => (
          <div className="glance__stat" key={s.label}>
            <dt className="glance__label">{s.label}</dt>
            <dd className="glance__value">{fmtCompact(s.value)}</dd>
          </div>
        ))}
      </dl>

      {data.featured.length > 0 && (
        <section className="featured" aria-label="Featured groups">
          <h2 className="featured__heading">Featured groups</h2>
          <p className="featured__sub">
            How much of each group is assembled. A big group with a short bar is a gap.
          </p>
          <div className="featured__grid">
            {data.featured.map((f) => (
              <FeaturedCard key={f.taxid} clade={f} />
            ))}
          </div>
        </section>
      )}

      <p className="hero__meta">
        Data from NCBI, Annotrieve, and ENA. Percentages are the share of species with a genome
        assembly.
      </p>
    </div>
  );
}

/** One featured-group card: friendly name, species count, and an assembly-coverage
 *  meter, linking into the group's dashboard. */
function FeaturedCard({ clade }: { clade: FeaturedClade }) {
  const pct = clade.assembly_percent;
  const label = cladeLabel(clade.taxid) ?? clade.name;
  return (
    <Link to={`/clade/${clade.taxid}`} className="featured__card">
      <span className="featured__name">{label}</span>
      <span className="featured__species">{fmt(clade.species)} species</span>
      <div
        className="featured__bar"
        role="img"
        aria-label={`${fmtPct(pct)}% of ${label} species have a genome assembly`}
      >
        <div className="featured__bar-fill" style={{ width: `${Math.max(Math.min(pct, 100), 1.5)}%` }} />
      </div>
      <span className="featured__cov">{fmtPct(pct)}% assembled</span>
    </Link>
  );
}
