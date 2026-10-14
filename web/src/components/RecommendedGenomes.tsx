import { Link } from "react-router";

import { getAssemblies } from "../api/queries";
import type { AssemblyRecord, Taxon } from "../api/types";
import { useAsync } from "../hooks/useAsync";
import { cladePath, isUnit } from "../lib/clade";
import { fmt, fmtBp, fmtPct } from "../lib/format";
import { AssemblyBadges, LevelBadge } from "./RecordBrowser";

/** The first few rows of Records: for a group, the recommended assembly of its
 *  best species; for a species, its own best assemblies. */
export default function RecommendedGenomes({ clade }: { clade: Taxon }) {
  const unit = isUnit(clade);
  const page = useAsync(
    () => getAssemblies(clade.taxid, { best_per_species: !unit, limit: unit ? 3 : 5 }),
    [clade.taxid],
  );
  const total = page.data?.total;

  return (
    <section className="panel summary__wide" aria-labelledby="genomes-title">
      <div className="panel__head">
        <h2 className="panel__title" id="genomes-title">
          Recommended genomes
        </h2>
        {total !== undefined && (
          // A group's count of species here also holds its hybrids, which the
          // coverage counts leave out, so it isn't repeated next to them.
          <Link to={cladePath(clade.taxid, "records")}>
            {unit ? `All ${fmt(total)} ${total === 1 ? "assembly" : "assemblies"}` : "All species"} →
          </Link>
        )}
      </div>
      <p className="panel__sub">
        {unit ? "Its best assemblies" : "The best assembly of each species"}: reference genomes
        first, then the most complete.
      </p>
      {page.error ? (
        <p className="notice notice--error notice--inline">
          Could not load the assemblies.{" "}
          <button type="button" className="link-btn" onClick={page.reload}>
            Try again
          </button>
        </p>
      ) : !page.data ? (
        <p className="notice notice--inline">Loading…</p>
      ) : (
        <table className="bd-table sum-table">
          <thead>
            <tr>
              <th scope="col">Organism</th>
              <th scope="col">Assembly</th>
              <th scope="col">Level</th>
              <th scope="col" className="bd-num">
                Contig N50
              </th>
              <th scope="col">Annotation</th>
            </tr>
          </thead>
          <tbody>
            {page.data.results.map((a) => (
              <tr key={a.assembly_accession}>
                <td className="bd-name">
                  <Link className="rec-org" to={cladePath(a.taxid)}>
                    {a.organism_name}
                  </Link>
                </td>
                <td data-label="Assembly">
                  <span className="rec-acc">{a.assembly_accession}</span>
                  <AssemblyBadges a={a} />
                </td>
                <td data-label="Level">
                  {a.assembly_level ? <LevelBadge level={a.assembly_level} /> : "—"}
                </td>
                <td className="bd-num" data-label="Contig N50">
                  {a.contig_n50 ? fmtBp(a.contig_n50) : "—"}
                </td>
                <td data-label="Annotation">{annotationText(a)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

/** "BUSCO 96.9%", "Not scored" or "None yet". */
export function annotationText(a: Pick<AssemblyRecord, "annotations" | "best_busco">): string {
  if (a.best_busco !== null) return `BUSCO ${fmtPct(a.best_busco)}%`;
  return a.annotations > 0 ? "Not scored" : "None yet";
}
