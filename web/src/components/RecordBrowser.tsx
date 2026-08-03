import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { getAnnotations, getAssemblies } from "../api/queries";
import type {
  AnnotationRecord,
  AnnotationSort,
  AssemblyRecord,
  AssemblySort,
} from "../api/types";
import { fmt, fmtBp, fmtPct } from "../lib/format";

const PAGE = 20;
type Tab = "assemblies" | "annotations";
type Record = AssemblyRecord | AnnotationRecord;

const ASSEMBLY_SORTS: { value: AssemblySort; label: string }[] = [
  { value: "release_date", label: "Newest" },
  { value: "contig_n50", label: "Contig N50" },
  { value: "total_sequence_length", label: "Genome size" },
];
const ANNOTATION_SORTS: { value: AnnotationSort; label: string }[] = [
  { value: "busco_complete", label: "BUSCO" },
  { value: "protein_coding_count", label: "Gene count" },
  { value: "release_date", label: "Newest" },
];

/** Accumulating pager: fetches page 0 whenever `resetKey` changes (tab / sort /
 *  taxon), and appends further pages on `loadMore` without dropping the rows
 *  already on screen. Stale responses are ignored via the active flag. */
function usePagedRecords(
  fetchPage: (offset: number) => Promise<{ items: Record[]; total: number }>,
  resetKey: string,
) {
  const [items, setItems] = useState<Record[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string>();
  const [curKey, setCurKey] = useState(resetKey);

  // When the key changes (tab / sort / taxon) drop the stale rows *synchronously*
  // in render, before the refetch lands — otherwise the render right after a tab
  // flip would hand assembly rows to the annotation table (or vice-versa) and
  // crash on the missing fields. Idiomatic "reset state on prop change".
  if (curKey !== resetKey) {
    setCurKey(resetKey);
    setItems([]);
    setTotal(0);
    setLoading(true);
    setError(undefined);
  }

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(undefined);
    fetchPage(0).then(
      (r) => active && (setItems(r.items), setTotal(r.total), setLoading(false)),
      (e) => active && (setError(e instanceof Error ? e.message : String(e)), setLoading(false)),
    );
    return () => {
      active = false;
    };
    // fetchPage is recreated per render; resetKey is the intended trigger.
  }, [resetKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const loadMore = useCallback(() => {
    setLoadingMore(true);
    fetchPage(items.length).then(
      (r) => (setItems((cur) => [...cur, ...r.items]), setTotal(r.total), setLoadingMore(false)),
      (e) => (setError(e instanceof Error ? e.message : String(e)), setLoadingMore(false)),
    );
  }, [fetchPage, items.length]);

  return { items, total, loading, loadingMore, error, loadMore };
}

/** The per-record drill-down: individual genome assemblies and functional
 *  annotations anywhere under a taxon, with direct download links (FASTA / GFF).
 *  Tabbed, sortable, and paged with "load more". Mount with `key={taxid}` so a
 *  new root resets the tab/sort/pages. */
export default function RecordBrowser({ taxid }: { taxid: number }) {
  const [tab, setTab] = useState<Tab>("assemblies");
  const [asmSort, setAsmSort] = useState<AssemblySort>("release_date");
  const [annSort, setAnnSort] = useState<AnnotationSort>("busco_complete");

  const fetchPage = useCallback(
    (offset: number): Promise<{ items: Record[]; total: number }> =>
      tab === "assemblies"
        ? getAssemblies(taxid, { sort: asmSort, limit: PAGE, offset }).then((r) => ({
            items: r.items,
            total: r.total,
          }))
        : getAnnotations(taxid, { sort: annSort, limit: PAGE, offset }).then((r) => ({
            items: r.items,
            total: r.total,
          })),
    [taxid, tab, asmSort, annSort],
  );

  const resetKey = `${taxid}:${tab}:${tab === "assemblies" ? asmSort : annSort}`;
  const { items, total, loading, loadingMore, error, loadMore } = usePagedRecords(
    fetchPage,
    resetKey,
  );

  const sorts = tab === "assemblies" ? ASSEMBLY_SORTS : ANNOTATION_SORTS;
  const sortValue = tab === "assemblies" ? asmSort : annSort;
  const setSort = (v: string) =>
    tab === "assemblies" ? setAsmSort(v as AssemblySort) : setAnnSort(v as AnnotationSort);

  return (
    <section className="rec" aria-labelledby="rec-title">
      <header className="rec__head">
        <h2 className="rec__title" id="rec-title">
          Browse the data
        </h2>
        <p className="rec__sub">Individual records under this group, with direct download links.</p>
      </header>

      <div className="rec__controls">
        <div className="rec__tabgroup">
          <span className="control__label">Show</span>
          <div className="rec__tabs" role="tablist" aria-label="Record type">
            {(["assemblies", "annotations"] as Tab[]).map((t) => (
              <button
                key={t}
                type="button"
                role="tab"
                aria-selected={tab === t}
                className={`seg-btn${tab === t ? " seg-btn--on" : ""}`}
                onClick={() => setTab(t)}
              >
                {t === "assemblies" ? "Assemblies" : "Annotations"}
              </button>
            ))}
          </div>
        </div>
        <label className="control control--inline">
          <span className="control__label">Sort by</span>
          <select
            className="control__select"
            value={sortValue}
            onChange={(e) => setSort(e.target.value)}
          >
            {sorts.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error ? (
        <p className="notice notice--error">{error}</p>
      ) : loading ? (
        <p className="notice">Loading records…</p>
      ) : items.length === 0 ? (
        <p className="notice">
          No {tab} recorded under this group yet.
          {tab === "annotations" && " Annotations cover a reference-quality subset of genomes."}
        </p>
      ) : (
        <>
          <div className="bd__table-wrap">
            {tab === "assemblies" ? (
              <AssemblyTable items={items as AssemblyRecord[]} />
            ) : (
              <AnnotationTable items={items as AnnotationRecord[]} />
            )}
          </div>
          <div className="rec__foot">
            <span>
              Showing <strong>{fmt(items.length)}</strong> of <strong>{fmt(total)}</strong> {tab}
            </span>
            {items.length < total && (
              <button type="button" className="dl" onClick={loadMore} disabled={loadingMore}>
                {loadingMore ? "Loading…" : `Load ${Math.min(PAGE, total - items.length)} more`}
              </button>
            )}
          </div>
        </>
      )}
    </section>
  );
}

/** Scientific name linking to the record's own dashboard (its taxid may be a
 *  strain below species). */
function Organism({ taxid, name }: { taxid: number; name: string }) {
  return (
    <Link className="rec-org" to={`/clade/${taxid}`}>
      {name}
    </Link>
  );
}

function AssemblyTable({ items }: { items: AssemblyRecord[] }) {
  return (
    <table className="bd-table rec-table">
      <thead>
        <tr>
          <th scope="col">Organism</th>
          <th scope="col">Assembly</th>
          <th scope="col">Level</th>
          <th scope="col" className="bd-num">
            Genome size
          </th>
          <th scope="col" className="bd-num">
            Contig N50
          </th>
          <th scope="col">Released</th>
          <th scope="col">Download</th>
        </tr>
      </thead>
      <tbody>
        {items.map((a) => (
          <tr key={a.assembly_accession}>
            <td className="bd-name">
              <Organism taxid={a.taxid} name={a.organism} />
            </td>
            <td>
              <span className="rec-acc">{a.assembly_accession}</span>
              {a.source_database && <span className="rec-tag">{a.source_database}</span>}
            </td>
            <td>
              {a.assembly_level ? <LevelBadge level={a.assembly_level} /> : <Dash />}
            </td>
            <td className="bd-num">{a.total_sequence_length ? fmtBp(a.total_sequence_length) : <Dash />}</td>
            <td className="bd-num">{a.contig_n50 ? fmtBp(a.contig_n50) : <Dash />}</td>
            <td className="rec-date">{a.release_date ?? <Dash />}</td>
            <td>
              {a.download_url ? (
                <a className="rec-dl" href={a.download_url} target="_blank" rel="noreferrer">
                  NCBI ↗
                </a>
              ) : (
                <Dash />
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function AnnotationTable({ items }: { items: AnnotationRecord[] }) {
  return (
    <table className="bd-table rec-table">
      <thead>
        <tr>
          <th scope="col">Organism</th>
          <th scope="col">Source</th>
          <th scope="col" className="bd-num">
            BUSCO
          </th>
          <th scope="col" className="bd-num">
            Genes
          </th>
          <th scope="col">Assembly</th>
          <th scope="col">Released</th>
          <th scope="col">Download</th>
        </tr>
      </thead>
      <tbody>
        {items.map((a) => (
          <tr key={a.annotation_id}>
            <td className="bd-name">
              <Organism taxid={a.taxid} name={a.organism} />
            </td>
            <td>
              <span className="rec-src" title={a.provider ?? undefined}>
                {a.source_database ?? "—"}
              </span>
            </td>
            <td className="bd-num">
              {a.busco_complete !== null ? (
                <span title={a.busco_lineage ?? undefined}>{fmtPct(a.busco_complete)}%</span>
              ) : (
                <Dash />
              )}
            </td>
            <td className="bd-num">
              {a.protein_coding_count !== null ? fmt(a.protein_coding_count) : <Dash />}
            </td>
            <td>
              <span className="rec-acc">{a.assembly_accession ?? "—"}</span>
            </td>
            <td className="rec-date">{a.release_date ?? <Dash />}</td>
            <td>
              {a.gff_url ? (
                <a className="rec-dl" href={a.gff_url} target="_blank" rel="noreferrer">
                  GFF ↗
                </a>
              ) : (
                <Dash />
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Assembly level as a small chip carrying its ordinal-ramp colour dot. */
function LevelBadge({ level }: { level: string }) {
  const key = level.replace("Complete Genome", "complete").split(" ")[0].toLowerCase();
  const known = ["complete", "chromosome", "scaffold", "contig"].includes(key);
  return (
    <span className="rec-level">
      {known && <span className={`comp__dot comp__seg--${key}`} aria-hidden="true" />}
      {level}
    </span>
  );
}

function Dash() {
  return <span className="rec-dash">—</span>;
}
