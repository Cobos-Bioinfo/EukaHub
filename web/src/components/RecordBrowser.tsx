import { useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router";

import {
  annotationsReportUrl,
  assembliesReportUrl,
  getAnnotations,
  getAssemblies,
  getAssemblyChecks,
  getTaxaStats,
  type AssemblyFilters,
} from "../api/queries";
import type {
  AnnotationRecord,
  AnnotationSort,
  AssemblyLevel,
  AssemblyRecord,
  AssemblySort,
  Taxon,
} from "../api/types";
import { useAsync, type AsyncState } from "../hooks/useAsync";
import { cladePath, isUnit } from "../lib/clade";
import { fmt, fmtBp, fmtBpRound, fmtPct } from "../lib/format";

const PAGE = 25;

const LEVELS: { key: AssemblyLevel; label: string }[] = [
  { key: "complete", label: "Complete genome" },
  { key: "chromosome", label: "Chromosome" },
  { key: "scaffold", label: "Scaffold" },
  { key: "contig", label: "Contig" },
];
const MIN_CONTIG_N50 = [100_000, 1_000_000, 10_000_000];
const ASSEMBLY_SORTS: { value: AssemblySort; label: string }[] = [
  { value: "recommended", label: "Recommended" },
  { value: "contig_n50", label: "Contig N50" },
  { value: "scaffold_n50", label: "Scaffold N50" },
  { value: "total_sequence_length", label: "Genome size" },
  { value: "release_date", label: "Newest" },
];
const ANNOTATION_SORTS: { value: AnnotationSort; label: string }[] = [
  { value: "busco_complete", label: "BUSCO" },
  { value: "protein_coding_count", label: "Gene count" },
  { value: "release_date", label: "Newest" },
];
const ORDER = "reference genomes first, then the most complete level, then the longest contig N50";
// A size this many times under or over the median of the species' assemblies is marked.
const SIZE_OUTLIER = 2;

interface Page<T> {
  total: number;
  next?: string | null;
  previous?: string | null;
  results: T[];
}

/** One page of a list at a time, following its cursors. Back to the first page
 *  whenever `key` (the list's taxon, filters and sort) changes. */
function usePages<T>(fetchPage: (cursor?: string) => Promise<Page<T>>, key: string) {
  const [at, setAt] = useState<{ key: string; cursor?: string; offset: number }>({ key, offset: 0 });
  const current = at.key === key ? at : { key, offset: 0 };
  const page = useAsync(() => fetchPage(current.cursor), [key, current.cursor]);
  const go = (cursor: string | null | undefined, offset: number) => {
    if (cursor) setAt({ key, cursor, offset });
  };
  return {
    page,
    offset: current.offset,
    next: () => go(page.data?.next, current.offset + (page.data?.results.length ?? 0)),
    previous: () => go(page.data?.previous, Math.max(0, current.offset - PAGE)),
  };
}

/** The search-parameter helpers both lists use: a value that equals its default
 *  is left out of the address. */
function useParam() {
  const [params, setParams] = useSearchParams();
  const set = (changes: Record<string, string | null>) =>
    setParams(
      (p) => {
        const q = new URLSearchParams(p);
        for (const [key, value] of Object.entries(changes)) {
          if (value === null) q.delete(key);
          else q.set(key, value);
        }
        return q;
      },
      { replace: true },
    );
  return { params, set };
}

/** The genome assemblies on a group or below it: filters on the left, one
 *  recommended assembly per species by default. Filters and sort are kept in
 *  the address, so a view can be linked to. */
export function AssemblyRecords({ clade }: { clade: Taxon }) {
  const unit = isUnit(clade);
  const { params, set } = useParam();
  const chosenLevels = (params.get("level")?.split(",") ?? []).filter((l) =>
    LEVELS.some((x) => x.key === l),
  ) as AssemblyLevel[];
  const levels = chosenLevels.length > 0 ? chosenLevels : LEVELS.map((l) => l.key);
  const minN50 = Number(params.get("n50"));
  const filters: AssemblyFilters = {
    best_per_species: !unit && params.get("one") !== "0",
    ebp_standard: params.get("ebp") === "1",
    reference: params.get("ref") === "1",
    assembly_level: levels.length < LEVELS.length ? levels : undefined,
    min_contig_n50: MIN_CONTIG_N50.includes(minN50) ? minN50 : undefined,
  };
  const sort = ASSEMBLY_SORTS.find((s) => s.value === params.get("sort"))?.value ?? "recommended";
  const filtered = Boolean(
    filters.ebp_standard || filters.reference || filters.assembly_level || filters.min_contig_n50,
  );
  const clear = () => set({ ebp: null, ref: null, level: null, n50: null });

  const key = JSON.stringify([clade.taxid, filters, sort]);
  const { page, offset, next, previous } = usePages(
    (cursor) => getAssemblies(clade.taxid, { ...filters, sort_by: sort, limit: PAGE, cursor }),
    key,
  );
  const total = page.data?.total;
  const what = filters.best_per_species
    ? `species, the best assembly of each`
    : total === 1
      ? "assembly"
      : "assemblies";

  return (
    <div className="records">
      <AssemblyFilterPanel
        clade={clade}
        unit={unit}
        filters={filters}
        levels={levels}
        filtered={filtered}
        set={set}
        clear={clear}
      />
      <section className="records__results" aria-label="Assemblies">
        <ResultsBar
          count={total === undefined ? undefined : `${fmt(total)} ${what}`}
          note={
            sort === "recommended"
              ? `Recommended: ${ORDER}.`
              : filters.best_per_species
                ? `Each species shows its best assembly: ${ORDER}.`
                : undefined
          }
          sorts={ASSEMBLY_SORTS}
          sort={sort}
          onSort={(value) => set({ sort: value === "recommended" ? null : value })}
          download={
            total ? assembliesReportUrl(clade.taxid, { ...filters, sort_by: sort }) : undefined
          }
          total={total}
        />
        <Results
          page={page}
          empty={
            <p className="notice">
              No assemblies match these filters.{" "}
              <button type="button" className="link-btn" onClick={clear}>
                Clear the filters
              </button>
            </p>
          }
        >
          {(items) => (
            <>
              <AssemblyTable items={items} perSpecies={Boolean(filters.best_per_species)} />
              <Pager
                offset={offset}
                shown={items.length}
                total={page.data?.total ?? 0}
                unit={filters.best_per_species ? "species" : "assemblies"}
                hasPrevious={Boolean(page.data?.previous)}
                hasNext={Boolean(page.data?.next)}
                onPrevious={previous}
                onNext={next}
              />
            </>
          )}
        </Results>
      </section>
    </div>
  );
}

function AssemblyFilterPanel({
  clade,
  unit,
  filters,
  levels,
  filtered,
  set,
  clear,
}: {
  clade: Taxon;
  unit: boolean;
  filters: AssemblyFilters;
  levels: AssemblyLevel[];
  filtered: boolean;
  set: (changes: Record<string, string | null>) => void;
  clear: () => void;
}) {
  // Open beside the list on a wide screen; folded above it on a phone.
  const [open, setOpen] = useState(() => !window.matchMedia("(max-width: 640px)").matches);
  const checks = useAsync(() => getAssemblyChecks(), []);
  const ebp = useAsync(
    () => getAssemblies(clade.taxid, { ebp_standard: true, limit: 1 }).then((p) => p.total),
    [clade.taxid],
  );
  const toggleLevel = (level: AssemblyLevel, on: boolean) => {
    const next = LEVELS.map((l) => l.key).filter((l) => (l === level ? on : levels.includes(l)));
    set({ level: next.length === LEVELS.length ? null : next.join(",") });
  };

  return (
    <details
      className="rec-filters"
      open={open}
      onToggle={(e) => setOpen(e.currentTarget.open)}
    >
      <summary className="rec-filters__title">Filters</summary>
      <div className="rec-filters__body">
        {!unit && (
          <fieldset className="rec-filters__group">
            <legend>Species</legend>
            <label className="rec-check">
              <input
                type="checkbox"
                checked={Boolean(filters.best_per_species)}
                onChange={(e) => set({ one: e.target.checked ? null : "0" })}
              />
              <span>Best assembly per species</span>
            </label>
            <p className="rec-filters__note">Subspecies and strains count with their species.</p>
          </fieldset>
        )}
        <fieldset className="rec-filters__group">
          <legend>Quality</legend>
          <label className="rec-check">
            <input
              type="checkbox"
              checked={Boolean(filters.ebp_standard)}
              onChange={(e) => set({ ebp: e.target.checked ? "1" : null })}
            />
            <span>Meets the EBP standard</span>
            {ebp.data !== undefined && <span className="rec-check__count">{fmt(ebp.data)}</span>}
          </label>
          <label className="rec-check">
            <input
              type="checkbox"
              checked={Boolean(filters.reference)}
              onChange={(e) => set({ ref: e.target.checked ? "1" : null })}
            />
            <span>Reference genomes only</span>
            <span className="rec-check__count">{fmt(clade.composition.reference)}</span>
          </label>
          {checks.data && (
            <p className="rec-filters__note">
              EBP standard: contig N50 of {fmtBpRound(checks.data.ebp_min_contig_n50)} or more
              and scaffold N50 of {fmtBpRound(checks.data.ebp_min_scaffold_n50)} or more.
            </p>
          )}
        </fieldset>
        <fieldset className="rec-filters__group">
          <legend>Assembly level</legend>
          {LEVELS.map((l) => {
            const on = levels.includes(l.key);
            return (
              <label key={l.key} className="rec-check">
                <input
                  type="checkbox"
                  checked={on}
                  // The last level left stays on: no level at all would list nothing.
                  disabled={on && levels.length === 1}
                  onChange={(e) => toggleLevel(l.key, e.target.checked)}
                />
                <span>{l.label}</span>
                <span className="rec-check__count">{fmt(clade.composition[l.key])}</span>
              </label>
            );
          })}
        </fieldset>
        <fieldset className="rec-filters__group">
          <legend>
            <label htmlFor="rec-min-n50">Minimum contig N50</label>
          </legend>
          <select
            id="rec-min-n50"
            className="control__select"
            value={filters.min_contig_n50 ?? ""}
            onChange={(e) => set({ n50: e.target.value || null })}
          >
            <option value="">Any</option>
            {MIN_CONTIG_N50.map((v) => (
              <option key={v} value={v}>
                {fmtBpRound(v)}
              </option>
            ))}
          </select>
        </fieldset>
        {filtered && (
          <button type="button" className="link-btn rec-filters__clear" onClick={clear}>
            Clear the filters
          </button>
        )}
      </div>
    </details>
  );
}

/** The annotations on a group or below it, best BUSCO first by default. */
export function AnnotationRecords({ clade }: { clade: Taxon }) {
  const { params, set } = useParam();
  const sort =
    ANNOTATION_SORTS.find((s) => s.value === params.get("sort"))?.value ?? "busco_complete";
  const key = JSON.stringify([clade.taxid, sort]);
  const { page, offset, next, previous } = usePages(
    (cursor) => getAnnotations(clade.taxid, { sort_by: sort, limit: PAGE, cursor }),
    key,
  );
  const total = page.data?.total;

  return (
    <section className="records__results" aria-label="Annotations">
      <ResultsBar
        count={total === undefined ? undefined : `${fmt(total)} ${total === 1 ? "annotation" : "annotations"}`}
        sorts={ANNOTATION_SORTS}
        sort={sort}
        onSort={(value) => set({ sort: value === "busco_complete" ? null : value })}
        download={total ? annotationsReportUrl(clade.taxid, sort) : undefined}
        total={total}
      />
      <Results page={page} empty={<p className="notice">No annotations under this group yet.</p>}>
        {(items) => (
          <>
            <AnnotationTable items={items} />
            <Pager
              offset={offset}
              shown={items.length}
              total={page.data?.total ?? 0}
              unit="annotations"
              hasPrevious={Boolean(page.data?.previous)}
              hasNext={Boolean(page.data?.next)}
              onPrevious={previous}
              onNext={next}
            />
          </>
        )}
      </Results>
    </section>
  );
}

function ResultsBar<S extends string>({
  count,
  note,
  sorts,
  sort,
  onSort,
  download,
  total,
}: {
  count?: string;
  note?: string;
  sorts: { value: S; label: string }[];
  sort: S;
  onSort: (value: S) => void;
  download?: string;
  total?: number;
}) {
  return (
    <div className="records__bar">
      <div className="records__summary">
        <p className="records__count" aria-live="polite">
          {count ?? "Counting…"}
        </p>
        {note && <p className="records__note">{note}</p>}
      </div>
      <div className="records__actions">
        <label className="control">
          <span className="control__label">Sort by</span>
          <select
            className="control__select"
            value={sort}
            onChange={(e) => onSort(e.target.value as S)}
          >
            {sorts.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        {download && total !== undefined && (
          <a className="dl dl--primary" href={download} download>
            Download {fmt(total)} {total === 1 ? "row" : "rows"} (TSV)
          </a>
        )}
      </div>
    </div>
  );
}

function Results<T>({
  page,
  empty,
  children,
}: {
  page: AsyncState<Page<T>>;
  empty: React.ReactNode;
  children: (items: T[]) => React.ReactNode;
}) {
  if (page.error) {
    return (
      <p className="notice notice--error" role="alert">
        Could not load the records: {page.error}{" "}
        <button type="button" className="link-btn" onClick={page.reload}>
          Try again
        </button>
      </p>
    );
  }
  if (!page.data) return <p className="notice">Loading records…</p>;
  if (page.data.results.length === 0) return <>{empty}</>;
  return <>{children(page.data.results)}</>;
}

function Pager({
  offset,
  shown,
  total,
  unit,
  hasPrevious,
  hasNext,
  onPrevious,
  onNext,
}: {
  offset: number;
  shown: number;
  total: number;
  unit: string;
  hasPrevious: boolean;
  hasNext: boolean;
  onPrevious: () => void;
  onNext: () => void;
}) {
  return (
    <nav className="rec__foot" aria-label="Pages">
      <span>
        Showing {fmt(offset + 1)} to {fmt(offset + shown)} of {fmt(total)} {unit}
      </span>
      {(hasPrevious || hasNext) && (
        <span className="rec__pages">
          <button type="button" className="dl" onClick={onPrevious} disabled={!hasPrevious}>
            Previous
          </button>
          <button type="button" className="dl" onClick={onNext} disabled={!hasNext}>
            Next
          </button>
        </span>
      )}
    </nav>
  );
}

/** The median genome size of each species of `items`, from their quality stats;
 *  empty while it loads or if it fails, which leaves every size unmarked. */
function useSpeciesMedians(items: AssemblyRecord[]): Map<number, number> {
  const ids = [...new Set(items.map((a) => a.species_taxid))].sort((x, y) => x - y);
  const stats = useAsync(
    () => (ids.length > 0 ? getTaxaStats({ taxids: ids, limit: ids.length }) : Promise.resolve(null)),
    [ids.join(",")],
  );
  const medians = new Map<number, number>();
  for (const t of stats.data?.results ?? []) {
    const size = t.stats.genome_size;
    if (size) medians.set(t.taxid, size);
  }
  return medians;
}

/** How far an assembly's size is from its species' median, when it is an outlier:
 *  "5.4% of the species median (2.70 Gb)"; else null. A reference genome is never
 *  one: it is the species' yardstick, and a median of a few partial assemblies
 *  can be far below it. */
function sizeFlag(a: AssemblyRecord, median: number | undefined): string | null {
  const size = a.total_sequence_length;
  if (!size || !median || a.refseq_category === "reference genome") return null;
  const ratio = size / median;
  if (ratio >= 1 / SIZE_OUTLIER && ratio <= SIZE_OUTLIER) return null;
  const share = ratio < 1 ? `${fmtPct(ratio * 100)}% of` : `${ratio.toFixed(1)} times`;
  return `${share} the species median (${fmtBp(median)})`;
}

/** The first column names each record's organism: the species, or one of its
 *  subspecies and strains. */
function AssemblyTable({ items, perSpecies }: { items: AssemblyRecord[]; perSpecies: boolean }) {
  const { search } = useLocation();
  const medians = useSpeciesMedians(items);
  const flags = items.map((a) => sizeFlag(a, medians.get(a.species_taxid)));
  return (
    <>
      <div className="bd__table-wrap">
        <table className="bd-table rec-table">
          <thead>
            <tr>
              <th scope="col">Organism</th>
              <th scope="col">Assembly</th>
              <th scope="col">Level</th>
              <th scope="col" className="bd-num">
                Contig N50
              </th>
              <th scope="col" className="bd-num">
                Scaffold N50
              </th>
              <th scope="col" className="bd-num">
                Size
              </th>
              <th scope="col">
                <abbr title="Annotations of this assembly, and the best BUSCO completeness among them">
                  Annotations
                </abbr>
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((a, i) => {
              const more = (a.species_assemblies ?? 1) - 1;
              return (
                <tr key={a.assembly_accession}>
                  <td className="bd-name">
                    <Link className="rec-org" to={cladePath(a.taxid)}>
                      {a.organism_name}
                    </Link>
                    {perSpecies && more > 0 && (
                      <Link className="rec-sub" to={`${cladePath(a.species_taxid, "records")}${search}`}>
                        {fmt(more)} more {more === 1 ? "assembly" : "assemblies"}
                      </Link>
                    )}
                  </td>
                  <td data-label="Assembly">
                    <span className="rec-acc">{a.assembly_accession}</span>
                    {a.download_url && (
                      <a className="rec-dl" href={a.download_url} target="_blank" rel="noreferrer">
                        NCBI ↗
                      </a>
                    )}
                    <AssemblyBadges a={a} />
                    {a.release_date && <span className="rec-sub">Released {a.release_date}</span>}
                  </td>
                  <td data-label="Level">
                    {a.assembly_level ? <LevelBadge level={a.assembly_level} /> : <Dash />}
                  </td>
                  <td className="bd-num" data-label="Contig N50">
                    {a.contig_n50 ? fmtBp(a.contig_n50) : <Dash />}
                  </td>
                  <td className="bd-num" data-label="Scaffold N50">
                    {a.scaffold_n50 ? fmtBp(a.scaffold_n50) : <Dash />}
                  </td>
                  <td className="bd-num" data-label="Size">
                    {a.total_sequence_length ? fmtBp(a.total_sequence_length) : <Dash />}
                    {flags[i] && <span className="rec-size-flag">{flags[i]}</span>}
                  </td>
                  <td data-label="Annotations">{annotationsText(a)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {flags.some(Boolean) && (
        <p className="records__foot-note">
          A size under half or over twice the median of its species' assemblies is marked,
          except on reference genomes: the assembly may hold only part of the genome, such as
          one chromosome, or extra sequence, such as contamination or both haplotypes.
        </p>
      )}
    </>
  );
}

/** "None", "1, not scored" or "4, BUSCO 96.9%" (the best of them). */
export function annotationsText(a: Pick<AssemblyRecord, "annotations" | "best_busco">): string {
  if (a.annotations === 0) return "None";
  return a.best_busco === null
    ? `${fmt(a.annotations)}, not scored`
    : `${fmt(a.annotations)}, BUSCO ${fmtPct(a.best_busco)}%`;
}

export function AssemblyBadges({ a }: { a: AssemblyRecord }) {
  const reference = a.refseq_category === "reference genome";
  if (!reference && !a.ebp_standard) return null;
  return (
    <span className="rec-badges">
      {reference && <span className="rec-badge rec-badge--ref">Reference</span>}
      {a.ebp_standard && <span className="rec-badge rec-badge--ebp">EBP standard</span>}
    </span>
  );
}

function AnnotationTable({ items }: { items: AnnotationRecord[] }) {
  return (
    <div className="bd__table-wrap">
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
                <Link className="rec-org" to={cladePath(a.taxid)}>
                  {a.organism_name}
                </Link>
              </td>
              <td data-label="Source">
                <span className="rec-src" title={a.provider ?? undefined}>
                  {a.source_database ?? "—"}
                </span>
              </td>
              <td className="bd-num" data-label="BUSCO">
                {a.busco_complete !== null ? (
                  <span title={a.busco_lineage ?? undefined}>{fmtPct(a.busco_complete)}%</span>
                ) : (
                  <Dash />
                )}
              </td>
              <td className="bd-num" data-label="Genes">
                {a.protein_coding_count !== null ? fmt(a.protein_coding_count) : <Dash />}
              </td>
              <td data-label="Assembly">
                <span className="rec-acc">{a.assembly_accession ?? "—"}</span>
              </td>
              <td className="rec-date" data-label="Released">
                {a.release_date ?? <Dash />}
              </td>
              <td data-label="Download">
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
    </div>
  );
}

/** Assembly level as a small chip carrying its ordinal-ramp colour dot. */
export function LevelBadge({ level }: { level: string }) {
  const key = level.replace("Complete Genome", "complete").split(" ")[0].toLowerCase();
  const known = LEVELS.some((l) => l.key === key);
  return (
    <span className="rec-level">
      {known && <span className={`comp__dot comp__seg--${key}`} aria-hidden="true" />}
      {level === "Complete Genome" ? "Complete" : level}
    </span>
  );
}

function Dash() {
  return <span className="rec-dash">—</span>;
}
