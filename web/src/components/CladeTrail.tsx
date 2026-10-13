import { useEffect, useId, useRef, useState } from "react";
import { Link, useLocation } from "react-router";

import type { Taxon } from "../api/types";
import { useCurrentClade } from "../hooks/useCurrentClade";
import { cladePath, viewFor } from "../lib/clade";
import { SPINE_TAXIDS } from "../lib/taxonomy";

/** The current group's lineage in the top bar: the first two ranks, a "…" button
 *  listing the ones in between, and the last two (on a phone, `compact`: "…", the
 *  parent and the group). Every link keeps the current view. */
export default function CladeTrail({ compact = false }: { compact?: boolean }) {
  const current = useCurrentClade();
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLLIElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const popId = useId();
  const { pathname } = useLocation();

  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  if (!current?.clade) return null;
  const { clade, view } = current;
  const hops = clade.lineage.filter((t) => !SPINE_TAXIDS.has(t.taxid));
  const tail = hops.slice(-2);
  const head = hops.length > 4 ? hops.slice(0, 2) : hops.slice(0, -2);
  const between = hops.length > 4 ? hops.slice(2, -2) : [];
  const shown = compact ? [] : head;
  const folded = compact ? [...head, ...between] : between;
  const link = (t: Taxon) => <Link to={cladePath(t.taxid, viewFor(t, view))}>{t.name}</Link>;

  return (
    <nav className={"trail" + (compact ? " trail--compact" : "")} aria-label="Current group">
      <ol className="trail__list">
        {shown.map((t) => (
          <li key={t.taxid} className="trail__item">
            {link(t)}
          </li>
        ))}
        {folded.length > 0 && (
          <li
            className="trail__item trail__more"
            ref={boxRef}
            onKeyDown={(e) => {
              if (e.key === "Escape" && open) {
                setOpen(false);
                buttonRef.current?.focus();
              }
            }}
          >
            <button
              type="button"
              ref={buttonRef}
              className="trail__more-btn"
              aria-expanded={open}
              aria-controls={popId}
              aria-label={`Show the ${folded.length} ranks ${compact ? "above" : "in between"}`}
              onClick={() => setOpen((v) => !v)}
            >
              …
            </button>
            <ul id={popId} className="trail__pop" hidden={!open}>
              {folded.map((t) => (
                <li key={t.taxid}>
                  <Link className="trail__pop-link" to={cladePath(t.taxid, viewFor(t, view))}>
                    <span>{t.name}</span>
                    <span className="trail__pop-rank">{t.rank}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </li>
        )}
        {tail.map((t) => (
          <li key={t.taxid} className="trail__item">
            {t.taxid === clade.taxid ? (
              <span className="trail__current" aria-current="page">
                {t.name}
              </span>
            ) : (
              link(t)
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}
