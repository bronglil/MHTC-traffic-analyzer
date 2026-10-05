import { Link, NavLink, Route, Routes } from "react-router-dom";
import VideosPage from "./pages/VideosPage";
import WorkspacePage from "./pages/WorkspacePage";
import AnalysisPage from "./pages/AnalysisPage";
import BatchNewPage from "./pages/BatchNewPage";
import BatchPage from "./pages/BatchPage";
import BatchesPage from "./pages/BatchesPage";

export default function App() {
  return (
    <div className="min-h-screen">
      <header className="border-b border-line bg-surface-1">
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-3">
          <Link to="/" className="flex items-center gap-2 font-semibold">
            <svg viewBox="0 0 24 24" className="h-6 w-6 text-accent" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="6" width="18" height="12" rx="3" />
              <circle cx="8" cy="12" r="2" />
              <circle cx="16" cy="12" r="2" />
            </svg>
            Traffic Vision
          </Link>
          <span className="hidden text-sm text-ink-3 sm:inline">Vehicle detection, tracking &amp; counting</span>
          <nav className="ml-auto flex gap-1 text-sm">
            {[["/", "Videos"], ["/batches", "Batches"]].map(([to, label]) => (
              <NavLink key={to} to={to} end={to === "/"}
                className={({ isActive }) => `rounded-md px-2.5 py-1 ${isActive ? "bg-surface font-medium" : "text-ink-2 hover:bg-surface"}`}>
                {label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">
        <Routes>
          <Route path="/" element={<VideosPage />} />
          <Route path="/videos/:videoId" element={<WorkspacePage />} />
          <Route path="/analyses/:analysisId" element={<AnalysisPage />} />
          <Route path="/batches" element={<BatchesPage />} />
          <Route path="/batches/new" element={<BatchNewPage />} />
          <Route path="/batches/:batchId" element={<BatchPage />} />
          <Route path="*" element={<p className="text-ink-2">Page not found.</p>} />
        </Routes>
      </main>
    </div>
  );
}
