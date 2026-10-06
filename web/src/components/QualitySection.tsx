import type { AssemblyComposition, QualityStatConfig, QualityStatValue } from "../api/types";
import { fmt, fmtPct, fmtQuality } from "../lib/format";

// The four assembly levels, best-to-worst by contiguity. Colour comes from an
// ordinal blue ramp (validated with the dataviz --ordinal check, light + dark)
// applied via the `--lvl-*` tokens in index.css, so it re-anchors per theme.
const LEVELS = [
  { key: "complete", label: "Complete", help: "Complete genome" },
  { key: "chromosome", label: "Chromosome", help: "Chromosome-level" },
  { key: "scaffold", label: "Scaffold", help: "Scaffold-level" },
  { key: "contig", label: "Contig", help: "Contig-level" },
] as const;

/** The enrichment "Data quality" band for a taxon: its quality stats (BUSCO,
 *  gene count, genome size, N50) as stat tiles, plus an assembly contiguity bar
 *  from the additive composition counts. Shown on every dashboard (clade /
 *  species / leaf); the full record lists live in the drill-down browser below. */
export default function QualitySection({
  quality,
  stats,
  assemblies,
  annotations,
  composition,
}: {
  quality: QualityStatConfig[];
  stats: QualityStatValue[];
  assemblies: number;
  annotations: number;
  composition: AssemblyComposition;
}) {
  // Nothing to show for a clade with no assemblies and no annotations.
  if (assemblies === 0 && annotations === 0) return null;

  const values = new Map(stats.map((s) => [s.key, s.value]));
  return (
    <section className="quality" aria-labelledby="quality-title">
      <header className="quality__head">
        <h2 className="quality__title" id="quality-title">
          Data quality
        </h2>
        <p className="quality__sub">
          Assembly and annotation quality across this group&apos;s records.
        </p>
      </header>

      <div className="quality__tiles">
        {quality.map((q) => (
          <QualityTile
            key={q.key}
            config={q}
            value={values.get(q.key) ?? null}
            total={q.source === "annotation" ? annotations : assemblies}
          />
        ))}
      </div>

      <CompositionBar composition={composition} />
    </section>
  );
}

/** One quality stat tile: label, the value (median/best), and a caption
 *  naming the record set it was computed over. */
function QualityTile({
  config,
  value,
  total,
}: {
  config: QualityStatConfig;
  value: number | null;
  total: number;
}) {
  const noun = config.source === "annotation" ? "annotation" : "assembly";
  const nouns = config.source === "annotation" ? "annotations" : "assemblies";
  const has = value !== null;
  const caption =
    total > 0 ? `over ${fmt(total)} ${total === 1 ? noun : nouns}` : `no ${nouns} yet`;
  return (
    <article className="qtile" title={config.help}>
      <span className="qtile__label">{config.card_title}</span>
      <span className={`qtile__value${has ? "" : " qtile__value--empty"}`}>
        {fmtQuality(value, config.fmt)}
      </span>
      <span className="qtile__cap">{caption}</span>
    </article>
  );
}

/** Assembly contiguity as an ordinal stacked bar: the share of a clade's
 *  assemblies at each level (Complete → Contig), plus the reference-genome
 *  count. Segments grow proportionally (flex-grow = count) so zero levels
 *  collapse; each carries a hover title with its exact count + share. */
function CompositionBar({ composition }: { composition: AssemblyComposition }) {
  const counts = LEVELS.map((l) => ({
    ...l,
    n: composition[l.key as keyof AssemblyComposition],
  }));
  const total = counts.reduce((sum, c) => sum + c.n, 0);
  if (total === 0) return null;

  return (
    <div className="comp">
      <div className="comp__head">
        <span className="comp__title">Assembly contiguity</span>
        <span className="comp__total">
          {fmt(total)} {total === 1 ? "assembly" : "assemblies"}
        </span>
      </div>

      <div
        className="comp__bar"
        role="img"
        aria-label={`Assembly levels: ${counts
          .filter((c) => c.n > 0)
          .map((c) => `${c.label} ${fmtPct((c.n / total) * 100)}%`)
          .join(", ")}`}
      >
        {counts
          .filter((c) => c.n > 0)
          .map((c) => (
            <span
              key={c.key}
              className={`comp__seg comp__seg--${c.key}`}
              style={{ flexGrow: c.n }}
              title={`${c.help}: ${fmt(c.n)} (${fmtPct((c.n / total) * 100)}%)`}
            />
          ))}
      </div>

      <div className="comp__legend">
        {counts.map((c) => (
          <span key={c.key} className="comp__key" data-zero={c.n === 0}>
            <span className={`comp__dot comp__seg--${c.key}`} aria-hidden="true" />
            {c.label}
            <span className="comp__count">{fmt(c.n)}</span>
          </span>
        ))}
        {composition.reference > 0 && (
          <span
            className="comp__ref"
            title="NCBI reference or representative genomes, a curated quality marker"
          >
            {fmt(composition.reference)} reference
          </span>
        )}
      </div>
    </div>
  );
}
