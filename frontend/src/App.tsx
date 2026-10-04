import { Link, Route, Routes } from "react-router-dom";
import VideosPage from "./pages/VideosPage";
import WorkspacePage from "./pages/WorkspacePage";
import AnalysisPage from "./pages/AnalysisPage";

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
          <span className="text-sm text-ink-3">Vehicle detection, tracking &amp; counting</span>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">
        <Routes>
          <Route path="/" element={<VideosPage />} />
          <Route path="/videos/:videoId" element={<WorkspacePage />} />
          <Route path="/analyses/:analysisId" element={<AnalysisPage />} />
          <Route path="*" element={<p className="text-ink-2">Page not found.</p>} />
        </Routes>
      </main>
    </div>
  );
}
