import { lazy, Suspense } from 'react';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout';

// Route-split: each page loads its own JS chunk on demand so the landing
// dashboard doesn't drag in the code for tabs the user hasn't visited yet.
const VideoPage = lazy(() =>
  import('./pages/VideoPage').then((m) => ({ default: m.VideoPage })),
);
const SystemPage = lazy(() =>
  import('./pages/SystemPage').then((m) => ({ default: m.SystemPage })),
);
const IncidentsPage = lazy(() =>
  import('./pages/IncidentsPage').then((m) => ({ default: m.IncidentsPage })),
);
const AuditPage = lazy(() =>
  import('./pages/AuditPage').then((m) => ({ default: m.AuditPage })),
);
const AnalysisPage = lazy(() =>
  import('./pages/AnalysisPage').then((m) => ({ default: m.AnalysisPage })),
);

export default function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Suspense
          fallback={
            <div style={{ padding: 40, color: '#9097A0' }}>Loading…</div>
          }
        >
          <Routes>
            <Route path="/" element={<VideoPage />} />
            <Route path="/incidents" element={<IncidentsPage />} />
            <Route path="/analysis" element={<AnalysisPage />} />
            <Route path="/system" element={<SystemPage />} />
            <Route path="/audit" element={<AuditPage />} />
            <Route path="*" element={<VideoPage />} />
          </Routes>
        </Suspense>
      </Layout>
    </BrowserRouter>
  );
}
