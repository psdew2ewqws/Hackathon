import { BrowserRouter, Route, Routes, useLocation } from 'react-router-dom';
import { Nav } from './components/Nav';
import { AdvisorDrawer } from './components/AdvisorDrawer';
import { AuthProvider } from './auth/AuthContext';
import { RequireAuth } from './auth/RequireAuth';
import { DashboardV2 } from './pages/DashboardV2';
import { ForecastPage } from './pages/Forecast';
import { LivePage } from './pages/Live';
import { SignalPage } from './pages/Signal';
import { LoginPage } from './pages/LoginPage';
import { IncidentsPage } from './pages/IncidentsPage';
import { SystemPage } from './pages/SystemPage';
import { AuditPage } from './pages/AuditPage';
import { AnalysisPage } from './pages/AnalysisPage';
import { SignalTimingPage } from './pages/SignalTimingPage';
import { LaneCalibrationPage } from './pages/LaneCalibrationPage';
import { ChatPage } from './pages/ChatPage';

function Shell({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const hideNav = location.pathname === '/login';
  return (
    <div style={{ minHeight: '100vh', background: '#0b0f14', color: '#e6edf3' }}>
      {!hideNav && <Nav />}
      {children}
      {!hideNav && <AdvisorDrawer />}
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter basename={import.meta.env.BASE_URL}>
      <AuthProvider>
        <Shell>
          <Routes>
            <Route path="/login" element={<LoginPage />} />

            <Route
              path="/"
              element={
                <RequireAuth minRole="viewer">
                  <LivePage />
                </RequireAuth>
              }
            />
            <Route
              path="/dashboard"
              element={
                <RequireAuth minRole="viewer">
                  <DashboardV2 />
                </RequireAuth>
              }
            />
            <Route
              path="/signal"
              element={
                <RequireAuth minRole="operator">
                  <SignalPage />
                </RequireAuth>
              }
            />
            <Route
              path="/signal-timing"
              element={
                <RequireAuth minRole="operator">
                  <SignalTimingPage />
                </RequireAuth>
              }
            />
            <Route
              path="/forecast"
              element={
                <RequireAuth minRole="operator">
                  <ForecastPage />
                </RequireAuth>
              }
            />
            <Route
              path="/incidents"
              element={
                <RequireAuth minRole="operator">
                  <IncidentsPage />
                </RequireAuth>
              }
            />
            <Route
              path="/history"
              element={
                <RequireAuth minRole="operator">
                  <AnalysisPage />
                </RequireAuth>
              }
            />
            <Route
              path="/system"
              element={
                <RequireAuth minRole="admin">
                  <SystemPage />
                </RequireAuth>
              }
            />
            <Route
              path="/audit"
              element={
                <RequireAuth minRole="admin">
                  <AuditPage />
                </RequireAuth>
              }
            />
            <Route
              path="/lanes"
              element={
                <RequireAuth minRole="operator">
                  <LaneCalibrationPage />
                </RequireAuth>
              }
            />
            <Route
              path="/chat"
              element={
                <RequireAuth minRole="operator">
                  <ChatPage />
                </RequireAuth>
              }
            />
            <Route
              path="*"
              element={
                <RequireAuth minRole="viewer">
                  <LivePage />
                </RequireAuth>
              }
            />
          </Routes>
        </Shell>
      </AuthProvider>
    </BrowserRouter>
  );
}
