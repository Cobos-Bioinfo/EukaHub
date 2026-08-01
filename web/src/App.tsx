import { Link, Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";

import RootPicker from "./components/RootPicker";
import Dashboard from "./pages/Dashboard";
import TreePage from "./pages/TreePage";

// Default landing clade: Eukaryota (the whole surveyed tree).
const DEFAULT_TAXID = 2759;

export default function App() {
  const location = useLocation();
  // The Tree of Life goes full-bleed (near-fullscreen); every other page keeps
  // the centered content column.
  const isTree = location.pathname.startsWith("/tree/");
  return (
    <div className="app">
      <header className="app__bar">
        <Link className="app__brand" to={`/clade/${DEFAULT_TAXID}`}>
          Euka<span>Hub</span>
        </Link>
        <NavLink
          className={({ isActive }) => "app__nav" + (isActive ? " app__nav--active" : "")}
          to={`/tree/${DEFAULT_TAXID}`}
        >
          Tree of Life
        </NavLink>
        <RootPicker />
      </header>

      <main className={"app__main" + (isTree ? " app__main--full" : "")}>
        <Routes>
          <Route path="/" element={<Navigate to={`/clade/${DEFAULT_TAXID}`} replace />} />
          <Route path="/clade/:taxid" element={<Dashboard />} />
          <Route path="/tree/:taxid" element={<TreePage />} />
          <Route path="*" element={<p className="notice notice--error">Page not found.</p>} />
        </Routes>
      </main>

      <footer className="app__foot">
        Genomic resources across the eukaryotic tree of life — data from NCBI, Annotrieve
        and ENA, rebuilt periodically and served read-only.
      </footer>
    </div>
  );
}
