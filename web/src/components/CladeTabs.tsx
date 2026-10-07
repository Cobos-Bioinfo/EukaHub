import { Link } from "react-router";

import { useCurrentClade } from "../hooks/useCurrentClade";
import { VIEWS, cladePath, viewsOf } from "../lib/clade";

/** The current group's views as tabs: Summary, Data map, Records, Tree of Life
 *  and Gaps, or the ones it offers (see `viewsOf`). */
export default function CladeTabs() {
  const current = useCurrentClade();
  if (!current?.clade) return null;
  const { clade, view } = current;
  const offered = viewsOf(clade);

  return (
    <nav className="tabs" aria-label={`Views of ${clade.name}`}>
      {VIEWS.filter((v) => offered.includes(v.view)).map((v) => (
        <Link
          key={v.view}
          className={"tabs__tab" + (v.view === view ? " tabs__tab--on" : "")}
          to={cladePath(clade.taxid, v.view)}
          aria-current={v.view === view ? "page" : undefined}
        >
          {v.label}
        </Link>
      ))}
    </nav>
  );
}
