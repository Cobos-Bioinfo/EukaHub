import { Link } from "react-router";

import { getGaps, getOverview } from "../api/queries";
import type { FeaturedClade, GapItem } from "../api/types";
import RandomCladeButton from "../components/RandomCladeButton";
import RootPicker from "../components/RootPicker";
import { RandomIcon, SearchIcon, TreeIcon } from "../components/icons";
import { useAsync } from "../hooks/useAsync";
import { cladeLabel } from "../lib/clades";
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
      {/* The focal block (name, search, primary journeys) centres itself in the
          first screenful; the data strip below peeks at the fold to invite a scroll. */}
      <div className="hero__focal">
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

        <div className="hero__cta">
          <Link to={`/clade/${EUKARYOTA_TAXID}`} className="hero__btn hero__btn--primary">
            <SearchIcon size={17} />
            Explore Eukaryota
          </Link>
          <Link to={`/tree/${EUKARYOTA_TAXID}`} className="hero__btn hero__btn--tree">
            <TreeIcon size={17} />
            Tree of Life
          </Link>
          <RandomCladeButton
            className="hero__btn hero__btn--surprise"
            title="Jump to a random group"
          >
            <RandomIcon size={17} />
            Surprise me
          </RandomCladeButton>
        </div>
      </div>

      <LandingOverview />
      <LandingGaps />
    </section>
  );
}

/** A teaser for the "Where are the gaps?" leaderboard: the few eukaryotic orders
 *  with the most species still lacking a genome assembly, linking to the full
 *  view. Non-blocking and decorative — absent while loading or on error. */
function LandingGaps() {
  const { data } = useAsync(() => getGaps({ limit: 5, include_quality: false }), []);
  const items = data?.items ?? [];
  if (items.length === 0) return null;
  const maxGap = items[0].gap; // sorted gap-desc

  return (
    <section className="gaps-teaser" aria-label="Biggest data gaps">
      <div className="gaps-teaser__head">
        <h2 className="gaps-teaser__heading">Where are the gaps?</h2>
        <Link to="/gaps" className="gaps-teaser__all">
          See all gaps →
        </Link>
      </div>
      <p className="gaps-teaser__sub">
        The eukaryotic orders with the most species still lacking a genome assembly.
      </p>
      <ol className="gaps-teaser__list">
        {items.map((it) => (
          <TeaserRow key={it.taxid} item={it} maxGap={maxGap} />
        ))}
      </ol>
    </section>
  );
}

/** One teaser row: name, a gap-magnitude bar, and the missing-species count. */
function TeaserRow({ item, maxGap }: { item: GapItem; maxGap: number }) {
  const label = cladeLabel(item.taxid) ?? item.name;
  const width = Math.max((item.gap / maxGap) * 100, 3);
  return (
    <li>
      <Link to={`/clade/${item.taxid}`} className="gaps-teaser__row">
        <span className="gaps-teaser__name">{label}</span>
        <span
          className="gaps-teaser__bar"
          role="img"
          aria-label={`${fmt(item.gap)} species with no genome assembly`}
        >
          <span className="gaps-teaser__bar-fill" style={{ width: `${width}%` }} />
        </span>
        <span className="gaps-teaser__gap">
          <strong>{fmtCompact(item.gap)}</strong> missing
        </span>
      </Link>
    </li>
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
            The share of each group with a genome assembly and a functional annotation. A big
            group with short bars is a gap.
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
        assembly / functional annotation.
      </p>
    </div>
  );
}

/** One featured-group card: friendly name, species count, and two coverage
 *  meters (assembled / annotated), linking into the group's dashboard. */
function FeaturedCard({ clade }: { clade: FeaturedClade }) {
  const label = cladeLabel(clade.taxid) ?? clade.name;
  // The gap in absolute terms: species with no genome assembly yet. Reframes the
  // card around the app's thesis (scale, then coverage, then the concrete gap).
  const missing = Math.max(0, Math.round(clade.species * (1 - clade.assembly_percent / 100)));
  return (
    <Link to={`/clade/${clade.taxid}`} className="featured__card">
      <span className="featured__name">{label}</span>
      <span className="featured__species">{fmt(clade.species)} species</span>
      <CoverageMeter kind="assembled" name={label} label="Assembled" pct={clade.assembly_percent} />
      <CoverageMeter
        kind="annotated"
        name={label}
        label="Annotated"
        pct={clade.annotation_percent}
      />
      <span className="featured__gap">
        <strong>{fmtCompact(missing)}</strong> species with no genome yet
      </span>
    </Link>
  );
}

/** A labelled coverage meter (label + percent + bar) for a featured card. */
function CoverageMeter({
  kind,
  name,
  label,
  pct,
}: {
  kind: "assembled" | "annotated";
  name: string;
  label: string;
  pct: number;
}) {
  return (
    <div className="featured__metric">
      <div className="featured__metric-head">
        <span className="featured__metric-label">{label}</span>
        <span className="featured__metric-pct">{fmtPct(pct)}%</span>
      </div>
      <div
        className={`featured__bar featured__bar--${kind}`}
        role="img"
        aria-label={`${fmtPct(pct)}% of ${name} species are ${label.toLowerCase()}`}
      >
        <div className="featured__bar-fill" style={{ width: `${Math.max(Math.min(pct, 100), 1.5)}%` }} />
      </div>
    </div>
  );
}
