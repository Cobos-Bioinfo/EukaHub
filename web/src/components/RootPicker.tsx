import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";

import { getLineage, searchTaxa } from "../api/queries";
import type { TaxonRef } from "../api/types";

// EukaHub only covers the eukaryotic subtree; a TaxID outside it is rejected.
const EUKARYOTA_TAXID = 2759;

/** Search box that finds a clade by name or NCBI TaxID.
 *
 *  By default it opens the picked clade's dashboard. Pass ``onPick`` to intercept
 *  the selection instead (e.g. the compare view adds the group rather than
 *  navigating); ``placeholder`` overrides the input hint. */
export default function RootPicker({
  onPick,
  placeholder = "Search by name or TaxID, e.g. Primates or 9606",
}: {
  onPick?: (taxon: TaxonRef) => void;
  placeholder?: string;
} = {}) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<TaxonRef[]>([]);
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const query = q.trim();
    // All digits → look the taxon up directly by TaxID; otherwise search names.
    if (/^\d+$/.test(query)) {
      const timer = setTimeout(() => {
        getLineage(Number(query)).then(
          (t) =>
            t.lineage.some((a) => a.taxid === EUKARYOTA_TAXID)
              ? setResults([{ taxid: t.taxid, name: t.name, rank: t.rank }])
              : setResults([]),
          () => setResults([]),
        );
      }, 250);
      return () => clearTimeout(timer);
    }
    if (query.length < 2) {
      setResults([]);
      return;
    }
    const timer = setTimeout(() => {
      searchTaxa(query, 10).then(setResults, () => setResults([]));
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
    setOpen(false);
    if (onPick) onPick(taxon);
    else navigate(`/clade/${taxon.taxid}`);
  };

  return (
    <div className="picker" ref={boxRef}>
      <input
        className="picker__input"
        type="search"
        placeholder={placeholder}
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && results[0]) go(results[0]);
          if (e.key === "Escape") setOpen(false);
        }}
      />
      {open && results.length > 0 && (
        <ul className="picker__menu">
          {results.map((r) => (
            <li key={r.taxid}>
              <button type="button" className="picker__item" onClick={() => go(r)}>
                <span className="picker__name">{r.name}</span>
                <span className="picker__rank">{r.rank}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
