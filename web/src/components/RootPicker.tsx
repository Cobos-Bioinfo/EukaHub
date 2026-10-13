import { useEffect, useId, useRef, useState, type KeyboardEvent, type Ref } from "react";
import { useLocation, useNavigate } from "react-router";

import { getTaxon, searchTaxa, type SearchHit } from "../api/queries";
import type { TaxonRef } from "../api/types";
import { cladePath, parseCladePath } from "../lib/clade";
import { EUKARYOTA_TAXID } from "../lib/taxonomy";

/** A result row: a search hit, or the taxon a typed TaxID points to (which has
 *  no data flag, since the lineage lookup does not carry one). */
type Hit = TaxonRef & Partial<Pick<SearchHit, "context" | "has_data">>;

const CONTEXT_RANKS = ["class", "phylum", "kingdom"];

/** Search box that finds a clade by name or NCBI TaxID, as an ARIA combobox:
 *  arrow keys move through the results, Enter opens the highlighted one.
 *
 *  By default it opens the picked clade in the view you are on (its Summary from
 *  any other page). Pass ``onPick`` to intercept the selection instead (e.g. the
 *  compare view adds the group rather than navigating); ``placeholder`` overrides
 *  the input hint. */
export default function RootPicker({
  onPick,
  placeholder = "Search by name or TaxID",
  inputRef,
}: {
  onPick?: (taxon: TaxonRef) => void;
  placeholder?: string;
  inputRef?: Ref<HTMLInputElement>;
} = {}) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Hit[]>([]);
  const [similar, setSimilar] = useState(false);
  const [searched, setSearched] = useState(""); // the query the results belong to
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const boxRef = useRef<HTMLDivElement>(null);
  const latest = useRef(0);
  const listId = useId();

  useEffect(() => {
    const query = q.trim();
    const ticket = ++latest.current;
    const show = (hits: Hit[], close = false) => {
      if (ticket !== latest.current) return; // an older query answered late
      setResults(hits);
      setSimilar(close);
      setSearched(query);
      setActive(-1);
    };
    // All digits → look the taxon up directly by TaxID; otherwise search names.
    if (/^\d+$/.test(query)) {
      const timer = setTimeout(() => {
        getTaxon(Number(query)).then(
          (t) => {
            if (!t.lineage.some((a) => a.taxid === EUKARYOTA_TAXID)) return show([]);
            const above = t.lineage.slice(0, -1).filter((a) => CONTEXT_RANKS.includes(a.rank));
            show([
              {
                taxid: t.taxid,
                name: t.name,
                rank: t.rank,
                context: above.at(-1)?.name,
              },
            ]);
          },
          () => show([]),
        );
      }, 250);
      return () => clearTimeout(timer);
    }
    if (query.length < 3) {
      show([]);
      setSearched("");
      return;
    }
    const timer = setTimeout(() => {
      searchTaxa(query, 10).then(
        (hits) => show(hits, hits.length > 0 && hits[0].similar),
        () => show([]),
      );
    }, 250);
    return () => clearTimeout(timer);
  }, [q]);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const go = (taxon: TaxonRef) => {
    setQ("");
    setResults([]);
    setSearched("");
    setOpen(false);
    if (onPick) onPick({ taxid: taxon.taxid, name: taxon.name, rank: taxon.rank });
    else navigate(cladePath(taxon.taxid, parseCladePath(pathname)?.view));
  };

  const fresh = searched === q.trim();
  const noMatch = open && fresh && searched !== "" && results.length === 0;
  const expanded = open && results.length > 0;
  const optionId = (i: number) => `${listId}-opt-${i}`;
  const status =
    !fresh || searched === ""
      ? ""
      : results.length === 0
        ? `No matches for ${searched}`
        : `${results.length} ${similar ? "close spellings" : "results"}`;

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (results.length === 0) return;
      e.preventDefault();
      setOpen(true);
      const step = e.key === "ArrowDown" ? 1 : -1;
      setActive((i) => (i + step + results.length) % results.length);
    } else if (e.key === "Enter") {
      const pick = results[active] ?? results[0];
      if (pick) {
        e.preventDefault();
        go(pick);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
      setActive(-1);
    }
  };

  return (
    <div className="picker" ref={boxRef}>
      <input
        ref={inputRef}
        className="picker__input"
        type="search"
        role="combobox"
        aria-label={placeholder}
        aria-autocomplete="list"
        aria-expanded={expanded}
        aria-controls={listId}
        aria-activedescendant={expanded && active >= 0 ? optionId(active) : undefined}
        placeholder={placeholder}
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
      />
      <div className="picker__menu" hidden={!expanded && !noMatch}>
        {noMatch && (
          <p className="picker__note">
            No matches for “{searched}”. Try a scientific name, part of one, or a TaxID.
          </p>
        )}
        {expanded && similar && (
          <p className="picker__note">No names contain “{searched}”. Closest spellings:</p>
        )}
        <ul className="picker__list" id={listId} role="listbox" aria-label="Search results">
          {results.map((r, i) => (
            <li
              key={r.taxid}
              id={optionId(i)}
              role="option"
              aria-selected={i === active}
              className={"picker__item" + (i === active ? " picker__item--active" : "")}
              onMouseDown={(e) => e.preventDefault()}
              onMouseEnter={() => setActive(i)}
              onClick={() => go(r)}
            >
              <span className="picker__main">
                {r.has_data !== undefined && (
                  <span
                    className={"picker__dot" + (r.has_data ? " picker__dot--data" : "")}
                    title={r.has_data ? "Has data" : "No data yet"}
                  />
                )}
                <span className="picker__name">{r.name}</span>
                {r.has_data === false && <span className="sr-only">, no data yet</span>}
              </span>
              <span className="picker__rank">
                {r.rank}
                {r.context && <span className="picker__context"> in {r.context}</span>}
              </span>
            </li>
          ))}
        </ul>
      </div>
      <span className="sr-only" role="status" aria-live="polite">
        {status}
      </span>
    </div>
  );
}
