import { Link } from "react-router";

import { getAssemblies, getTaxa, type TaxonWithLineage } from "../api/queries";
import type { AssemblyRecord, Taxon } from "../api/types";
import { useAsync } from "../hooks/useAsync";
import { cladePath } from "../lib/clade";
import { fmt, fmtBp } from "../lib/format";
import { annotationText } from "./RecommendedGenomes";
import { AssemblyBadges } from "./RecordBrowser";

// The relatives looked through, nearest first. Taxonomy is not a phylogeny, so
// they are named by what they share ("same genus"), never as the closest.
const WALK = ["genus", "family", "order"];
const SHOWN = 3;

interface Relatives {
  group: Taxon;
  assemblies: AssemblyRecord[];
  rnaSeqRuns: Map<number, number>;
}

/** For a species with no data at all: the species of its genus with the best
 *  genome assemblies, or of its family or order when the genus has none. */
export default function SeeAlso({ clade }: { clade: TaxonWithLineage }) {
  const relatives = useAsync(() => findRelatives(clade), [clade.taxid]);
  const found = relatives.data;
  if (!found) return null;
  const { group, assemblies, rnaSeqRuns } = found;

  return (
    <section className="panel see-also" aria-labelledby="see-also-title">
      <div className="panel__head">
        <h2 className="panel__title" id="see-also-title">
          See also: relatives in the same {group.rank}
        </h2>
        <Link to={cladePath(group.taxid)}>
          Open {group.name}: {fmt(group.species)} species →
        </Link>
      </div>
      <p className="panel__sub">
        Species of <em>{group.name}</em> with the best genome assemblies.
      </p>
      <ul className="see-also__list">
        {assemblies.map((a) => {
          const runs = rnaSeqRuns.get(a.species_taxid) ?? 0;
          return (
            <li key={a.assembly_accession} className="see-also__card">
              <Link className="rec-org see-also__name" to={cladePath(a.taxid)}>
                {a.organism_name}
              </Link>
              <AssemblyBadges a={a} />
              <dl className="see-also__facts">
                <div>
                  <dt>Assembly</dt>
                  <dd>
                    {a.assembly_level ?? "Unknown"} level
                    {a.total_sequence_length ? `, ${fmtBp(a.total_sequence_length)}` : ""}
                  </dd>
                </div>
                <div>
                  <dt>Contig N50</dt>
                  <dd>{a.contig_n50 ? fmtBp(a.contig_n50) : "—"}</dd>
                </div>
                <div>
                  <dt>Annotation</dt>
                  <dd>{annotationText(a)}</dd>
                </div>
                <div>
                  <dt>RNA-Seq</dt>
                  <dd>{runs > 0 ? `${fmt(runs)} ${runs === 1 ? "run" : "runs"}` : "None yet"}</dd>
                </div>
              </dl>
              {a.download_url ? (
                <a className="rec-acc" href={a.download_url} target="_blank" rel="noreferrer">
                  {a.assembly_accession} ↗
                </a>
              ) : (
                <span className="rec-acc">{a.assembly_accession}</span>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** The nearest of the clade's genus, family and order with assemblies, its best
 *  species' recommended assemblies, and their RNA-Seq runs; null if none has any. */
async function findRelatives(clade: TaxonWithLineage): Promise<Relatives | null> {
  for (const rank of WALK) {
    const group = clade.lineage.find((t) => t.rank === rank && t.taxid !== clade.taxid);
    if (!group || group.resources.assemblies.total === 0) continue;
    const page = await getAssemblies(group.taxid, { best_per_species: true, limit: SHOWN });
    if (page.results.length === 0) continue;
    const taxa = await getTaxa({
      taxids: page.results.map((a) => a.species_taxid),
      limit: SHOWN,
    });
    const rnaSeqRuns = new Map(taxa.results.map((t) => [t.taxid, t.resources.rna_seq?.total ?? 0]));
    return { group, assemblies: page.results, rnaSeqRuns };
  }
  return null;
}
