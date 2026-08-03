import { Link } from "react-router";

import { getChildren } from "../api/queries";
import type { MetricConfig } from "../api/types";
import { useAsync } from "../hooks/useAsync";
import { fmt } from "../lib/format";

// How many infraspecific children to list; the rest live in the Tree of Life.
const MAX = 50;

/** Below-species taxa (subspecies, strains, varietas, isolates, ...) directly
 *  under a focused species or infraspecific node. Each carries its own data and
 *  is navigable, but is never counted toward this taxon's or any ancestor's
 *  totals — so it only appears here, when focused on the parent. Sorted so the
 *  data-rich ones surface first. Renders nothing when there are none. */
export default function SubspeciesSection({
  taxid,
  rank,
  metrics,
}: {
  taxid: number;
  rank: string;
  metrics: MetricConfig[];
}) {
  const children = useAsync(() => getChildren(taxid, { sort: "s_ass", limit: MAX }), [taxid]);

  const data = children.data;
  if (children.loading || !data || data.total === 0) return null;

  const heading = rank === "species" ? "Subspecies & strains" : "Finer subdivisions";
  return (
    <section className="bd" aria-label={heading}>
      <div className="bd__head">
        <h2 className="bd__title">{heading}</h2>
      </div>
      <p className="bd__sub" style={{ marginTop: "0.35rem" }}>
        {fmt(data.total)} infraspecific {data.total === 1 ? "taxon" : "taxa"} recorded here. Each has
        its own data and is not counted in the totals above.
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
            {data.items.map((it) => (
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

      {data.total > data.items.length && (
        <p className="bd__sub" style={{ marginTop: "0.6rem" }}>
          Showing the {data.items.length} with the most data. See them all in the{" "}
          <Link to={`/tree/${taxid}`}>Tree of Life</Link>.
        </p>
      )}
    </section>
  );
}
