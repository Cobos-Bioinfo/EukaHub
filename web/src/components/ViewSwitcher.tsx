import { Link } from "react-router-dom";

import { CompareIcon, DashboardIcon, MapIcon, TreeIcon } from "./icons";

export type CladeView = "dashboard" | "tree" | "map";

// Canonical order, matching the top nav: Dashboard, Tree of Life, Data map.
const VIEWS: {
  key: CladeView;
  label: string;
  to: (t: number) => string;
  Icon: typeof DashboardIcon;
}[] = [
  { key: "dashboard", label: "Dashboard", to: (t) => `/clade/${t}`, Icon: DashboardIcon },
  { key: "tree", label: "Tree of Life", to: (t) => `/tree/${t}`, Icon: TreeIcon },
  { key: "map", label: "Data map", to: (t) => `/map/${t}`, Icon: MapIcon },
];

/** Cross-navigation for one clade: CTA buttons to its other views (every view
 *  but the current one), in the same order as the top nav, plus an "Add to
 *  compare" shortcut. Rendered in the dashboard's sticky rail so it stays
 *  reachable while the page scrolls. */
export default function ViewSwitcher({
  taxid,
  name,
  current,
}: {
  taxid: number;
  name?: string;
  current: CladeView;
}) {
  const others = VIEWS.filter((v) => v.key !== current);
  return (
    <nav className="viewsw" aria-label={`Explore ${name ?? "this clade"} in other views`}>
      <span className="viewsw__label">
        Explore {name ? <em>{name}</em> : "this clade"}
      </span>
      {others.map(({ key, label, to, Icon }) => (
        <Link key={key} className={`viewsw__btn viewsw__btn--${key}`} to={to(taxid)}>
          <Icon size={17} />
          <span>{label}</span>
          <span className="viewsw__arrow" aria-hidden="true">
            →
          </span>
        </Link>
      ))}
      <Link className="viewsw__compare" to={`/compare?taxids=${taxid}`}>
        <CompareIcon size={15} />
        Add to compare
      </Link>
    </nav>
  );
}
