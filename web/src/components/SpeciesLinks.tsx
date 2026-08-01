import type { MetricConfig } from "../api/types";
import { externalUrl } from "../lib/format";

/** "Go get the data" links for a single species — NCBI (genomes & assemblies),
 *  Annotrieve (annotations), ENA (RNA-Seq). Reuses each metric's source URL, so
 *  it only appears on species-level dashboards. */
export default function SpeciesLinks({
  metrics,
  taxid,
}: {
  metrics: MetricConfig[];
  taxid: number;
}) {
  return (
    <section className="species-links" aria-label="External data sources">
      <h2 className="species-links__title">Get the data</h2>
      <p className="species-links__sub">Open this species at the source.</p>
      <div className="species-links__list">
        {metrics.map((m) => (
          <a
            key={m.key}
            className="species-links__item"
            href={externalUrl(m.external_url_template, taxid)}
            target="_blank"
            rel="noreferrer"
          >
            <span className="species-links__dot" style={{ background: m.color }} aria-hidden="true" />
            <span className="species-links__label">{m.card_title}</span>
            <span className="species-links__src">{m.external_source_name} ↗</span>
          </a>
        ))}
      </div>
    </section>
  );
}
