import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { searchTaxa } from "../api/queries";
import type { TaxonRef } from "../api/types";

/** Debounced name-search box that navigates to the chosen clade's dashboard. */
export default function RootPicker() {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<TaxonRef[]>([]);
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const query = q.trim();
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

  const go = (taxid: number) => {
    setQ("");
    setResults([]);
    setOpen(false);
    navigate(`/clade/${taxid}`);
  };

  return (
    <div className="picker" ref={boxRef}>
      <input
        className="picker__input"
        type="search"
        placeholder="Search a clade — e.g. Primates, Fungi…"
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && results[0]) go(results[0].taxid);
          if (e.key === "Escape") setOpen(false);
        }}
      />
      {open && results.length > 0 && (
        <ul className="picker__menu">
          {results.map((r) => (
            <li key={r.taxid}>
              <button type="button" className="picker__item" onClick={() => go(r.taxid)}>
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
