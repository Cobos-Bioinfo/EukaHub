import { Link, Navigate, Route, Routes } from "react-router-dom";

import RootPicker from "./components/RootPicker";
import Dashboard from "./pages/Dashboard";

// Default landing clade: Eukaryota (the whole surveyed tree).
const DEFAULT_TAXID = 2759;

export default function App() {
  return (
    <div className="app">
      <header className="app__bar">
        <Link className="app__brand" to={`/clade/${DEFAULT_TAXID}`}>
          Euka<span>Hub</span>
        </Link>
        <RootPicker />
      </header>

      <main className="app__main">
        <Routes>
          <Route path="/" element={<Navigate to={`/clade/${DEFAULT_TAXID}`} replace />} />
          <Route path="/clade/:taxid" element={<Dashboard />} />
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
