import { Link } from "react-router";

import { getChildren, getMeta } from "../api/queries";
import { useAsync } from "../hooks/useAsync";
import { cladePath } from "../lib/clade";
import { externalUrl, fmt, fmtDate } from "../lib/format";

// How many groups to list inside an empty clade; the rest are in the Tree of Life.
const MAX = 50;

/** What a taxon with no assembly, annotation or RNA-Seq run shows instead of
 *  four zero cards: a plain statement with the dataset date, a link to NCBI for
 *  anything newer, and for a group, the groups inside it so the visitor can keep
 *  browsing. */
export default function NoDataNotice({
  taxid,
  name,
  rank,
  isUnit,
  species,
  ncbiUrlTemplate,
}: {
  taxid: number;
  name: string;
  rank: string;
  isUnit: boolean;
  species: number;
  ncbiUrlTemplate?: string;
}) {
  const meta = useAsync(getMeta, []);
  const date = fmtDate(meta.data?.built_at);
  const asOf = date ? `As of the ${date} dataset, ` : "";
  const what = rank === "species" ? "species" : "taxon";

  return (
    <>
      <section className="nodata" aria-labelledby="nodata-title">
        <h2 className="nodata__title" id="nodata-title">
          {isUnit
            ? `No public genome data for this ${what} yet`
            : "No public genome data in this group yet"}
        </h2>
        <p className="nodata__text">
          {isUnit ? (
            <>
              {asOf}NCBI, Annotrieve and ENA hold no genome assemblies, annotations or RNA-Seq runs
              for <em>{name}</em>.
            </>
          ) : (
            <>
              {asOf}none of the {fmt(species)} species in {name} has a genome assembly, annotation
              or RNA-Seq run in NCBI, Annotrieve or ENA.
            </>
          )}
        </p>
        {ncbiUrlTemplate && (
          <a
            className="nodata__link"
            href={externalUrl(ncbiUrlTemplate, taxid)}
            target="_blank"
            rel="noreferrer"
          >
            Check NCBI for anything newer ↗
          </a>
        )}
      </section>
      {!isUnit && <ChildList taxid={taxid} name={name} />}
    </>
  );
}

/** The groups directly inside an empty clade, biggest first, as plain links. */
function ChildList({ taxid, name }: { taxid: number; name: string }) {
  const children = useAsync(() => getChildren(taxid, { limit: MAX }), [taxid]);
  const data = children.data;
  if (!data || data.total === 0) return null;
  return (
    <section className="bd" aria-labelledby="nodata-children">
      <h2 className="bd__title" id="nodata-children">
        Inside {name}
      </h2>
      <ul className="nodata__list">
        {data.results.map((c) => (
          <li key={c.taxid}>
            <Link to={`/clade/${c.taxid}`}>{c.name}</Link>{" "}
            <span className="nodata__meta">
              {c.rank}
              {c.n_rows > 1 ? `, ${fmt(c.n_rows)} species` : ""}
            </span>
          </li>
        ))}
      </ul>
      {data.total > data.results.length && (
        <p className="nodata__more">
          {fmt(data.total - data.results.length)} more in the{" "}
          <Link to={cladePath(taxid, "tree")}>Tree of Life</Link>.
        </p>
      )}
    </section>
  );
}
