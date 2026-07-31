import type { TaxonAbout } from "../api/types";

// Trim the extract to roughly one card's worth, cutting on a word boundary so
// we never slice mid-word. Mirrors Euka-Survey's fixed-height blurb.
const EXTRACT_MAX_CHARS = 320;

function trimExtract(text: string): string {
  if (text.length <= EXTRACT_MAX_CHARS) return text;
  return text.slice(0, EXTRACT_MAX_CHARS).replace(/\s+\S*$/, "") + "…";
}

/** The Wikipedia "About" card for the current taxon — thumbnail + blurb + link.
 *  Purely contextual: the caller renders it only when a summary exists. */
export default function AboutCard({ about }: { about: TaxonAbout }) {
  return (
    <aside className="about-card">
      {about.thumbnail && (
        <img
          className="about-card__thumb"
          src={about.thumbnail}
          alt={about.title}
          loading="lazy"
          width={104}
          height={104}
        />
      )}
      <div className="about-card__body">
        <h2 className="about-card__title">
          <span className="about-card__eyebrow">About</span>
          {about.title}
          {about.description && (
            <span className="about-card__desc"> · {about.description}</span>
          )}
        </h2>
        <p className="about-card__extract">{trimExtract(about.extract)}</p>
        <a
          className="about-card__link"
          href={about.url}
          target="_blank"
          rel="noreferrer"
        >
          Read more on Wikipedia ↗
        </a>
      </div>
    </aside>
  );
}
