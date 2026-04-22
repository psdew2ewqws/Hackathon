import { useState, type FormEvent } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';

export function LoginPage() {
  const { login, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const redirectTo =
    (location.state as { from?: string } | null)?.from ?? '/';

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (isAuthenticated) {
    // Already signed in; bounce to target.
    navigate(redirectTo, { replace: true });
  }

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      await login(username.trim(), password);
      navigate(redirectTo, { replace: true });
    } catch (err) {
      setError((err as Error).message || 'Login failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        background: '#0b0f14',
        color: '#e6edf3',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 20,
      }}
    >
      <form
        onSubmit={onSubmit}
        style={{
          width: '100%',
          maxWidth: 380,
          background: '#121820',
          border: '1px solid #1e2630',
          borderRadius: 10,
          padding: 28,
          font: '500 13px/1.55 system-ui, -apple-system, sans-serif',
        }}
      >
        <div
          style={{
            fontSize: 16,
            fontWeight: 600,
            letterSpacing: '.02em',
            marginBottom: 4,
          }}
        >
          Wadi Saqra · Traffic Ops
        </div>
        <div
          style={{
            color: '#9097A0',
            fontSize: 12,
            marginBottom: 20,
          }}
        >
          Sign in with your operator credentials.
        </div>

        {error && (
          <div
            role="alert"
            style={{
              marginBottom: 14,
              padding: '8px 12px',
              background: 'rgba(228,111,111,0.12)',
              border: '1px solid rgba(228,111,111,0.4)',
              borderRadius: 6,
              color: '#E46F6F',
              fontSize: 12,
            }}
          >
            {error}
          </div>
        )}

        <label style={{ display: 'block', marginBottom: 12 }}>
          <div style={{ fontSize: 11, color: '#9097A0', marginBottom: 4 }}>
            Username
          </div>
          <input
            name="username"
            type="text"
            autoComplete="username"
            autoFocus
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            style={inputStyle}
          />
        </label>

        <label style={{ display: 'block', marginBottom: 18 }}>
          <div style={{ fontSize: 11, color: '#9097A0', marginBottom: 4 }}>
            Password
          </div>
          <input
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            style={inputStyle}
          />
        </label>

        <button
          type="submit"
          disabled={busy || !username || !password}
          style={{
            width: '100%',
            padding: '10px 14px',
            background: busy ? '#1e2630' : '#66ff88',
            color: busy ? '#9097A0' : '#0b0f14',
            border: '1px solid #1e2630',
            borderRadius: 6,
            fontWeight: 600,
            fontSize: 13,
            cursor: busy ? 'not-allowed' : 'pointer',
          }}
        >
          {busy ? 'Signing in…' : 'Sign in'}
        </button>

        <div
          style={{
            marginTop: 20,
            paddingTop: 14,
            borderTop: '1px solid #1e2630',
            fontSize: 11,
            color: '#5A616B',
            lineHeight: 1.6,
          }}
        >
          Demo accounts: <code>viewer/viewer123</code> ·{' '}
          <code>operator/operator123</code> · <code>admin/admin123</code>
        </div>
      </form>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '8px 10px',
  background: '#0b0f14',
  color: '#e6edf3',
  border: '1px solid #1e2630',
  borderRadius: 6,
  fontSize: 13,
  fontFamily: 'inherit',
  outline: 'none',
};
