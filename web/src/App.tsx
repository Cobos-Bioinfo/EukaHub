import { useEffect, useRef, useState } from "react";
import { Link, Navigate, Route, Routes, useLocation, useParams, useSearchParams } from "react-router";

import { getMeta } from "./api/queries";
import CladeTabs from "./components/CladeTabs";
import CladeTrail from "./components/CladeTrail";
import { NotFound } from "./components/ErrorPage";
import HeaderMenu from "./components/HeaderMenu";
import RootPicker from "./components/RootPicker";
import ThemeToggle from "./components/ThemeToggle";
import { SearchIcon } from "./components/icons";
import { useAsync } from "./hooks/useAsync";
import { cladePath, parseCladePath, type CladeView } from "./lib/clade";
import { fmtDate } from "./lib/format";
import { EUKARYOTA_TAXID } from "./lib/taxonomy";
import BreakdownPage from "./pages/BreakdownPage";
import CladeLayout from "./pages/CladeLayout";
import ComparePage from "./pages/ComparePage";
import Faq from "./pages/Faq";
import GapsPage from "./pages/GapsPage";
import Landing from "./pages/Landing";
import Privacy from "./pages/Privacy";
import RecordsPage from "./pages/RecordsPage";
import SummaryPage from "./pages/SummaryPage";
import TreePage from "./pages/TreePage";

export default function App() {
  const { pathname } = useLocation();
  const route = parseCladePath(pathname);
  // On a phone the search box folds behind a button in the one-line top bar.
  const [searchOpen, setSearchOpen] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);
  useEffect(() => setSearchOpen(false), [pathname]);
  useEffect(() => {
    if (searchOpen) searchRef.current?.focus();
  }, [searchOpen]);

  return (
    <div className="app">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className={"app__bar" + (searchOpen ? " app__bar--search" : "")}>
        <div className="app__bar-inner">
          <Link className="app__brand" to="/">
            Euka<span>Hub</span>
          </Link>
          <CladeTrail />
          <RootPicker placeholder="Search species, groups or TaxIDs" inputRef={searchRef} />
          <div className="app__actions">
            <button
              type="button"
              className="app__icon-btn app__search-toggle"
              aria-label={searchOpen ? "Close search" : "Search species or groups"}
              aria-expanded={searchOpen}
              onClick={() => setSearchOpen((v) => !v)}
            >
              <SearchIcon size={19} />
            </button>
            <Link className="app__compare app__wide" to="/compare">
              Compare
            </Link>
            <ThemeToggle className="app__wide" />
            <HeaderMenu />
          </div>
        </div>
      </header>
      {route && (
        <div className="app__context">
          <div className="app__context-inner">
            <CladeTrail compact />
            <CladeTabs />
          </div>
        </div>
      )}

      <main
        id="main"
        tabIndex={-1}
        className={"app__main" + (route?.view === "tree" ? " app__main--full" : "")}
      >
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/clade/:taxid" element={<CladeLayout />}>
            <Route index element={<SummaryPage />} />
            <Route path="map" element={<BreakdownPage />} />
            <Route path="records" element={<RecordsPage />} />
            <Route path="tree" element={<TreePage />} />
            <Route path="gaps" element={<GapsPage />} />
            <Route path="*" element={<NotFound />} />
          </Route>
          <Route path="/map/:taxid" element={<LegacyRedirect view="map" />} />
          <Route path="/tree/:taxid" element={<LegacyRedirect view="tree" />} />
          <Route path="/gaps" element={<LegacyRedirect view="gaps" />} />
          <Route path="/compare" element={<ComparePage />} />
          <Route path="/faq" element={<Faq />} />
          <Route path="/privacy" element={<Privacy />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>

      <footer className="app__foot">
        <span>
          Public genomic resources across the eukaryotic tree of life. Data comes from NCBI,
          Annotrieve, and ENA, and is refreshed on a schedule.
        </span>
        <span className="app__foot-links">
          <Link className="app__foot-link" to="/privacy">
            Privacy
          </Link>
          <DataUpdated />
        </span>
      </footer>
    </div>
  );
}

/** The old addresses (`/map/:taxid`, `/tree/:taxid`, `/gaps`) open the same view
 *  of the same group under `/clade/:taxid`. The old data map kept its drill path
 *  in `?d=t1-t2` (the group shown is the last), and the old gaps page its group in
 *  `?root`. */
function LegacyRedirect({ view }: { view: CladeView }) {
  const { taxid } = useParams();
  const [params] = useSearchParams();
  const target =
    view === "gaps"
      ? params.get("root")
      : (params.get("d")?.split("-").filter(Boolean).at(-1) ?? taxid);
  const rest = new URLSearchParams(params);
  rest.delete("d");
  rest.delete("root");
  const query = rest.toString();
  const id = Number(target) > 0 ? Number(target) : EUKARYOTA_TAXID;
  return <Navigate replace to={cladePath(id, view) + (query ? `?${query}` : "")} />;
}

/** The app-wide "Data updated {date}" provenance stamp in the footer. Fetched
 *  non-blocking and omitted while loading, on error, or before the first build
 *  has stamped the DB (built_at null) — never load-bearing. */
function DataUpdated() {
  const { data } = useAsync(getMeta, []);
  const date = fmtDate(data?.built_at);
  if (!date) return null;
  return <span className="app__updated">Data updated {date}</span>;
}
