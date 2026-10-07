import { Link } from "react-router";

import { getChildren } from "../api/queries";
import type { MetricConfig } from "../api/types";
import { useAsync } from "../hooks/useAsync";
import { cladePath } from "../lib/clade";
import { fmt } from "../lib/format";
import { INFORMAL_SPECIES_RANK } from "../lib/taxonomy";

// How many infraspecific children to list; the rest live in the Tree of Life.
const MAX = 50;

/** Below-species taxa (subspecies, strains, varietas, isolates, ...) directly
 *  under a focused species or finer taxon, led by the records attached to the
 *  focused taxon itself, so the rows add up to the totals above. Sorted so the
 *  data-rich ones surface first. Renders nothing when there are none. */
export default function SubspeciesSection({
  taxid,
  name,
  rank,
  direct,
  metrics,
}: {
  taxid: number;
  name: string;
  rank: string;
  direct?: Record<string, number> | null;
  metrics: MetricConfig[];
}) {
  const children = useAsync(() => getChildren(taxid, { sort_by: "s_ass", limit: MAX }), [taxid]);

  const data = children.data;
  if (children.error) {
    return (
      <p className="notice notice--error notice--inline" role="alert">
        Could not load the finer taxa: {children.error}{" "}
        <button type="button" className="link-btn" onClick={children.reload}>
          Retry
        </button>
      </p>
    );
  }
  if (children.loading || !data || data.total === 0) return null;

  const heading =
    rank === "species" || rank === INFORMAL_SPECIES_RANK ? "Subspecies & strains" : "Finer subdivisions";
  return (
    <section className="bd" aria-label={heading}>
      <div className="bd__head">
        <h2 className="bd__title">{heading}</h2>
      </div>
      <p className="bd__sub" style={{ marginTop: "0.35rem" }}>
        {fmt(data.total)} finer {data.total === 1 ? "taxon" : "taxa"} recorded here. Their data is
        included in the totals above.
      </p>

      <div className="bd__table-wrap" style={{ marginTop: "1rem" }}>
        <table className="bd-table">
          <thead>
            <tr>
              <th>Taxon</th>
              <th>Rank</th>
              {metrics.map((m) => (
                <th key={m.key} className="bd-num">
                  <span
                    className="bd-metric__dot"
                    style={{ background: m.color }}
                    aria-hidden="true"
                  />
                  {m.card_title}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {direct && (
              <tr>
                <td className="bd-name">{name} (directly)</td>
                <td className="tree-outline__rank" data-label="Rank">
                  {rank}
                </td>
                {metrics.map((m) => (
                  <td key={m.key} className="bd-num" data-label={m.card_title}>
                    {fmt(direct[m.key] ?? 0)}
                  </td>
                ))}
              </tr>
            )}
            {data.results.map((it) => (
              <tr key={it.taxid}>
                <td className="bd-name">
                  <Link to={`/clade/${it.taxid}`}>{it.name}</Link>
                </td>
                <td className="tree-outline__rank" data-label="Rank">
                  {it.rank}
                </td>
                {metrics.map((m) => (
                  <td key={m.key} className="bd-num" data-label={m.card_title}>
                    {fmt(it.resources[m.key].total)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data.total > data.results.length && (
        <p className="bd__sub" style={{ marginTop: "0.6rem" }}>
          Showing the {data.results.length} with the most data. See them all in the{" "}
          <Link to={cladePath(taxid, "tree")}>Tree of Life</Link>.
        </p>
      )}
    </section>
  );
}
