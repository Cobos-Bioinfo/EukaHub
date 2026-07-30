import type { CSSProperties } from "react";

import type { MetricConfig, ResourceSummary } from "../api/types";
import { externalUrl, fmt, fmtPct } from "../lib/format";

/** One genomic-resource card: coverage count + percent bar + total + source. */
export default function MetricCard({
  config,
  value,
  taxid,
}: {
  config: MetricConfig;
  value: ResourceSummary;
  taxid: number;
}) {
  const pct = value.percent;
  return (
    <article className="card" style={{ "--metric-color": config.color } as CSSProperties}>
      <header className="card__head">
        <span className="card__dot" aria-hidden="true" />
        <h3 className="card__title" title={config.card_title_help ?? undefined}>
          {config.card_title}
        </h3>
        <a
          className="card__source"
          href={externalUrl(config.external_url_template, taxid)}
          target="_blank"
          rel="noreferrer"
        >
          {config.external_source_name} ↗
        </a>
      </header>

      <p className="card__stat">
        <span className="card__count" title={config.species_help}>
          {fmt(value.covered)}
        </span>
        <span className="card__pct">{fmtPct(pct)}%</span>
      </p>
      <p className="card__caption">species with data</p>

      <div
        className="card__bar"
        role="img"
        aria-label={`${fmtPct(pct)}% of species have ${config.card_title}`}
      >
        <div className="card__bar-fill" style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>

      <p className="card__total" title={config.total_help}>
        {config.total_label}: <strong>{fmt(value.total)}</strong>
      </p>
    </article>
  );
}
