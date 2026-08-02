import { Link, Route, Routes, useLocation } from "react-router-dom";

import HeaderMenu from "./components/HeaderMenu";
import RandomCladeButton from "./components/RandomCladeButton";
import RootPicker from "./components/RootPicker";
import ThemeToggle from "./components/ThemeToggle";
import { RandomIcon } from "./components/icons";
import BreakdownPage from "./pages/BreakdownPage";
import Dashboard from "./pages/Dashboard";
import Faq from "./pages/Faq";
import Landing from "./pages/Landing";
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
  return (
    <div className="app">
      <header className="app__bar">
        <Link className="app__brand" to="/">
          Euka<span>Hub</span>
        </Link>
        <Link className={navClass("/clade/")} to={`/clade/${DEFAULT_TAXID}`}>
          Dashboard
        </Link>
        <Link className={navClass("/tree/")} to={`/tree/${DEFAULT_TAXID}`}>
          Tree of Life
        </Link>
        <Link className={navClass("/map/")} to={`/map/${DEFAULT_TAXID}`}>
          Data map
        </Link>
        <div className="app__actions">
          <RootPicker />
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
          <Route path="/faq" element={<Faq />} />
          <Route path="*" element={<p className="notice notice--error">Page not found.</p>} />
        </Routes>
      </main>

      <footer className="app__foot">
        Public genomic resources across the eukaryotic tree of life. Data comes from NCBI,
        Annotrieve, and ENA, and is refreshed on a schedule.
      </footer>
    </div>
  );
}
