import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { roleAtLeast, useAuth, type Role } from './AuthContext';

interface RequireAuthProps {
  minRole: Role;
  children: ReactNode;
}

export function RequireAuth({ minRole, children }: RequireAuthProps) {
  const { user, loading, isAuthenticated } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div
        style={{
          padding: 40,
          color: '#9097A0',
          font: '500 13px system-ui, sans-serif',
        }}
      >
        Loading session…
      </div>
    );
  }

  if (!isAuthenticated || !user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  if (!roleAtLeast(user.role, minRole)) {
    return (
      <div
        style={{
          margin: '80px auto',
          maxWidth: 480,
          padding: 28,
          background: '#121820',
          border: '1px solid #1e2630',
          borderRadius: 10,
          color: '#e6edf3',
          font: '500 13px/1.55 system-ui, sans-serif',
          textAlign: 'center',
        }}
      >
        <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 8 }}>
          Access denied
        </div>
        <div style={{ color: '#9097A0' }}>
          This page requires <b style={{ color: '#E8B464' }}>{minRole}</b> role
          or higher. You are signed in as{' '}
          <b style={{ color: '#e6edf3' }}>
            {user.username} ({user.role})
          </b>
          .
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
