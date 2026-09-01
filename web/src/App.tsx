import { Link, Route, Routes, useLocation } from "react-router";

import { getMeta } from "./api/queries";
import HeaderMenu from "./components/HeaderMenu";
import RandomCladeButton from "./components/RandomCladeButton";
import RootPicker from "./components/RootPicker";
import ThemeToggle from "./components/ThemeToggle";
import { RandomIcon } from "./components/icons";
import { useAsync } from "./hooks/useAsync";
import { fmtDate } from "./lib/format";
import BreakdownPage from "./pages/BreakdownPage";
import ComparePage from "./pages/ComparePage";
import Dashboard from "./pages/Dashboard";
import Faq from "./pages/Faq";
import GapsPage from "./pages/GapsPage";
import Landing from "./pages/Landing";
import Privacy from "./pages/Privacy";
import TreePage from "./pages/TreePage";

// Default landing clade: Eukaryota (the whole surveyed tree).
const DEFAULT_TAXID = 2759;
const REPO_URL = "https://github.com/Cobos-Bioinfo/EukaHub";

export default function App() {
  const location = useLocation();
  // The Tree of Life goes full-bleed (near-fullscreen); every other page keeps
  // the centered content column.
  const isTree = location.pathname.startsWith("/tree/");
  // Nav links highlight for their whole route family (any clade, any tree).
  const navClass = (prefix: string) =>
    "app__nav" + (location.pathname.startsWith(prefix) ? " app__nav--active" : "");
  // Context-aware nav: on a taxon-scoped page carry the current group between the
  // views instead of resetting to Eukaryota, so hopping views keeps your place.
  const ctxMatch = location.pathname.match(/^\/(?:clade|map|tree)\/(\d+)/);
  const ctxTaxid = ctxMatch ? Number(ctxMatch[1]) : DEFAULT_TAXID;
  return (
    <div className="app">
      <header className="app__bar">
        <Link className="app__brand" to="/">
          Euka<span>Hub</span>
        </Link>
        <nav className="app__nav-group" aria-label="Primary">
          <Link className={navClass("/clade/")} to={`/clade/${ctxTaxid}`}>
            Dashboard
          </Link>
          <Link className={navClass("/tree/")} to={`/tree/${ctxTaxid}`}>
            Tree of Life
          </Link>
          <Link className={navClass("/map/")} to={`/map/${ctxTaxid}`}>
            Data map
          </Link>
          <Link className={navClass("/gaps")} to="/gaps">
            Gaps
          </Link>
          <Link className={navClass("/compare")} to="/compare">
            Compare
          </Link>
        </nav>
        <RootPicker />
        <div className="app__actions">
          <RandomCladeButton className="app__icon-btn" title="Surprise me, jump to a random group">
            <RandomIcon size={18} />
            <span className="sr-only">Surprise me, jump to a random group</span>
          </RandomCladeButton>
          <ThemeToggle />
          <a
            className="app__icon-btn"
            href={REPO_URL}
            target="_blank"
            rel="noreferrer"
            aria-label="View the source code on GitHub"
            title="Source on GitHub"
          >
            <svg viewBox="0 0 16 16" width="20" height="20" aria-hidden="true">
              <path
                fill="currentColor"
                d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"
              />
            </svg>
          </a>
          <HeaderMenu />
        </div>
      </header>

      <main className={"app__main" + (isTree ? " app__main--full" : "")}>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/clade/:taxid" element={<Dashboard />} />
          <Route path="/tree/:taxid" element={<TreePage />} />
          <Route path="/map/:taxid" element={<BreakdownPage />} />
          <Route path="/gaps" element={<GapsPage />} />
          <Route path="/compare" element={<ComparePage />} />
          <Route path="/faq" element={<Faq />} />
          <Route path="/privacy" element={<Privacy />} />
          <Route path="*" element={<p className="notice notice--error">Page not found.</p>} />
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

/** The app-wide "Data updated {date}" provenance stamp in the footer. Fetched
 *  non-blocking and omitted while loading, on error, or before the first build
 *  has stamped the DB (built_at null) — never load-bearing. */
function DataUpdated() {
  const { data } = useAsync(getMeta, []);
  const date = fmtDate(data?.built_at);
  if (!date) return null;
  return <span className="app__updated">Data updated {date}</span>;
}
