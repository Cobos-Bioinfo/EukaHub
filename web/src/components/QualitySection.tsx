import { getAnnotations, getAssemblies } from "../api/queries";
import type { AssemblyComposition, QualityStatConfig } from "../api/types";
import { useAsync } from "../hooks/useAsync";
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

/** The enrichment "Data quality" band for a taxon: live distribution stats
 *  (BUSCO, gene count, genome size, N50) as stat tiles, plus an assembly
 *  contiguity bar from the additive composition counts. Shown on every
 *  dashboard (clade / species / leaf). Fetches the two per-record endpoints
 *  with limit=1 — it needs only their subtree stats + totals, not records; the
 *  full lists live in the drill-down browser below. */
export default function QualitySection({
  taxid,
  quality,
  composition,
}: {
  taxid: number;
  quality: QualityStatConfig[];
  composition: AssemblyComposition;
}) {
  const assemblies = useAsync(() => getAssemblies(taxid, { limit: 1 }), [taxid]);
  const annotations = useAsync(() => getAnnotations(taxid, { limit: 1 }), [taxid]);

  // Merge the live stat values from both endpoints into one key -> value map.
  const values = new Map<string, number | null>();
  for (const s of assemblies.data?.stats ?? []) values.set(s.key, s.value);
  for (const s of annotations.data?.stats ?? []) values.set(s.key, s.value);

  const assemblyTotal = assemblies.data?.total ?? 0;
  const annotationTotal = annotations.data?.total ?? 0;
  const bothLoaded = !assemblies.loading && !annotations.loading;

  // Nothing to show for a clade with no assemblies and no annotations.
  if (bothLoaded && assemblyTotal === 0 && annotationTotal === 0) return null;

  const totalFor = (source: string) =>
    source === "annotation" ? annotationTotal : assemblyTotal;
  const loadedFor = (source: string) =>
    source === "annotation" ? !annotations.loading : !assemblies.loading;

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
            total={totalFor(q.source)}
            loaded={loadedFor(q.source)}
          />
        ))}
      </div>

      <CompositionBar composition={composition} />
    </section>
  );
}

/** One quality stat tile: label, the live value (median/best), and a caption
 *  naming the record set it was computed over. */
function QualityTile({
  config,
  value,
  total,
  loaded,
}: {
  config: QualityStatConfig;
  value: number | null;
  total: number;
  loaded: boolean;
}) {
  const noun = config.source === "annotation" ? "annotations" : "assemblies";
  const valueStr = !loaded ? "…" : fmtQuality(value, config.fmt);
  const has = loaded && value !== null;
  return (
    <article className="qtile" title={config.help}>
      <span className="qtile__label">{config.card_title}</span>
      <span className={`qtile__value${has ? "" : " qtile__value--empty"}`}>{valueStr}</span>
      <span className="qtile__cap">
        {total > 0 ? `over ${fmt(total)} ${noun}` : `no ${noun} yet`}
      </span>
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
        <span className="comp__total">{fmt(total)} assemblies</span>
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
