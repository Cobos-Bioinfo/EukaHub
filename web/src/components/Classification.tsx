import { Link } from "react-router";

import type { Taxon } from "../api/types";
import { cladePath } from "../lib/clade";
import { SPINE_TAXIDS } from "../lib/taxonomy";

// The ranks shown before "Show all": the ones most readers know.
const MAJOR = new Set([
  "domain",
  "superkingdom",
  "kingdom",
  "phylum",
  "class",
  "order",
  "family",
  "genus",
  "species",
]);

const label = (rank: string) =>
  rank === "no rank" ? "No rank" : rank.charAt(0).toUpperCase() + rank.slice(1);

/** A taxon's lineage as a list: its major ranks, then every rank on request.
 *  The trail at the top shows only its ends. */
export default function Classification({ lineage }: { lineage: Taxon[] }) {
  const ranks = lineage.filter((t) => !SPINE_TAXIDS.has(t.taxid));
  const major = ranks.filter((t) => MAJOR.has(t.rank));
  const self = ranks[ranks.length - 1];

  return (
    <section className="panel summary__narrow" aria-labelledby="classification-title">
      <h2 className="panel__title" id="classification-title">
        Classification
      </h2>
      <RankList taxa={major.includes(self) ? major : [...major, self]} self={self} />
      {ranks.length > major.length && (
        <details className="sum-ranks">
          <summary>Show all {ranks.length} ranks</summary>
          <RankList taxa={ranks} self={self} />
        </details>
      )}
    </section>
  );
}

function RankList({ taxa, self }: { taxa: Taxon[]; self: Taxon }) {
  return (
    <dl className="sum-class">
      {taxa.map((t) => (
        <div key={t.taxid} className="sum-class__row">
          <dt>{label(t.rank)}</dt>
          <dd>{t === self ? <strong>{t.name}</strong> : <Link to={cladePath(t.taxid)}>{t.name}</Link>}</dd>
        </div>
      ))}
    </dl>
  );
}
