import { Link } from "react-router-dom";

import RandomCladeButton from "../components/RandomCladeButton";
import RootPicker from "../components/RootPicker";
import { RandomIcon, TreeIcon } from "../components/icons";
import { HERO_CHIPS } from "../lib/clades";

// The whole surveyed tree: the default "explore everything" entry point.
const EUKARYOTA_TAXID = 2759;

/** The landing / hero page at `/`. Puts the EukaHub name front and centre, then
 *  gives a strong entry point: a prominent search, quick-jump chips, a
 *  random-clade button for undecided visitors, and the two primary journeys
 *  (dashboard + Tree of Life). Data-light by design, nothing is fetched on load. */
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

      <p className="hero__meta">
        Spanning ~1.8 million eukaryotic groups. Data from NCBI, Annotrieve, and ENA.
      </p>
    </section>
  );
}
