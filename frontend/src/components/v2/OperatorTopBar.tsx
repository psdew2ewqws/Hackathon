import { useEffect, useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { roleAtLeast, useAuth, type Role } from '../../auth/AuthContext';
import { apiUrl } from '../../api/client';

const NAV: Array<{ to: string; label: string; minRole: Role; end?: boolean }> = [
  { to: '/', label: 'Live', end: true, minRole: 'viewer' },
  { to: '/dashboard', label: 'Dashboard', minRole: 'viewer' },
  { to: '/signal', label: 'Signal', minRole: 'operator' },
  { to: '/forecast', label: 'Forecast', minRole: 'operator' },
  { to: '/incidents', label: 'Incidents', minRole: 'operator' },
  { to: '/history', label: 'History', minRole: 'operator' },
  { to: '/lanes', label: 'Lanes', minRole: 'operator' },
  { to: '/chat', label: 'Chat', minRole: 'operator' },
  { to: '/system', label: 'System', minRole: 'admin' },
];

interface BackendInfo {
  active: string;
  pending: string | null;
  label: string;
}
interface Health {
  tracker?: { running: boolean; fps: number };
}
interface SignalSnap {
  current?: { phase_name: string; signal_state: string; duration_seconds: number };
}

export function OperatorTopBar() {
  const { user, isAuthenticated, logout } = useAuth();
  const navigate = useNavigate();
  const [now, setNow] = useState<Date>(new Date());
  const [backend, setBackend] = useState<BackendInfo | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [signal, setSignal] = useState<SignalSnap | null>(null);

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const [b, h, s] = await Promise.all([
          fetch(apiUrl('/api/tracker/backend')).then((r) => (r.ok ? r.json() : null)),
          fetch(apiUrl('/api/health')).then((r) => (r.ok ? r.json() : null)),
          fetch(apiUrl('/api/signal/current')).then((r) => (r.ok ? r.json() : null)),
        ]);
        if (!alive) return;
        if (b) setBackend(b);
        if (h) setHealth(h);
        if (s) setSignal(s);
      } catch {
        /* keep last good */
      }
    };
    tick();
    const id = window.setInterval(tick, 2000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  const visible = NAV.filter((it) => roleAtLeast(user?.role, it.minRole));
  const fps = health?.tracker?.fps ?? 0;
  const running = !!health?.tracker?.running;
  const phase = signal?.current?.phase_name ?? '—';
  const phaseState = signal?.current?.signal_state ?? '';
  const phaseColor =
    phaseState === 'GREEN ON'
      ? 'var(--good)'
      : phaseState === 'YELLOW ON'
      ? 'var(--warn)'
      : phaseState === 'RED ON'
      ? 'var(--bad)'
      : 'var(--fg-faint)';
  const detectorLabel = backend?.label ?? '—';
  const clock = now.toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });

  const onLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  return (
    <header
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 50,
        height: 48,
        display: 'grid',
        gridTemplateColumns: 'auto 1fr auto',
        alignItems: 'center',
        gap: 18,
        padding: '0 18px',
        background: 'rgba(8, 9, 12, 0.85)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        borderBottom: '1px solid var(--border-soft)',
      }}
    >
      {/* Brand */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <div
          style={{
            width: 24,
            height: 24,
            borderRadius: 6,
            background:
              'linear-gradient(135deg, var(--accent) 0%, #d97706 100%)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            font: '700 12px var(--mono)',
            color: '#0a0a0a',
            letterSpacing: '-0.04em',
          }}
        >
          ti
        </div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <span
            style={{
              font: '600 13px var(--sans)',
              color: 'var(--fg-bright)',
              letterSpacing: '-0.01em',
            }}
          >
            Traffic Intel
          </span>
          <span
            style={{
              font: '500 9.5px var(--mono)',
              letterSpacing: '0.16em',
              textTransform: 'uppercase',
              color: 'var(--fg-faint)',
            }}
          >
            wadi saqra
          </span>
        </div>
      </div>

      {/* Nav */}
      <nav style={{ display: 'flex', gap: 2, justifyContent: 'center' }}>
        {visible.map((it) => (
          <NavLink
            key={it.to}
            to={it.to}
            end={it.end}
            style={({ isActive }) => ({
              padding: '6px 12px',
              borderRadius: 6,
              font: '500 12px var(--sans)',
              color: isActive ? 'var(--fg-bright)' : 'var(--fg-dim)',
              background: isActive ? 'var(--surface-2)' : 'transparent',
              border: '1px solid',
              borderColor: isActive ? 'var(--border)' : 'transparent',
              textDecoration: 'none',
              letterSpacing: '-0.005em',
              transition: 'background 0.15s, color 0.15s, border-color 0.15s',
            })}
          >
            {it.label}
          </NavLink>
        ))}
      </nav>

      {/* Status cluster + clock + user */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <Pill
          dot={running ? 'var(--good)' : 'var(--fg-faint)'}
          label="DET"
          value={detectorLabel}
          pulse={running}
        />
        <Pill
          dot={running ? 'var(--ai)' : 'var(--fg-faint)'}
          label="FPS"
          value={running ? fps.toFixed(1) : '—'}
        />
        <Pill
          dot={phaseColor}
          label="PHASE"
          value={`${phase} ${phaseState.replace(' ON', '')}`}
        />
        <span
          className="tabular"
          style={{
            font: '600 14px var(--mono)',
            color: 'var(--fg-bright)',
            letterSpacing: '-0.02em',
            minWidth: 76,
            textAlign: 'right',
          }}
        >
          {clock}
        </span>
        {isAuthenticated && user ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span
              style={{
                font: '500 11px var(--mono)',
                color: 'var(--fg-dim)',
                letterSpacing: '-0.005em',
              }}
            >
              {user.username}{' '}
              <span style={{ color: 'var(--accent)' }}>· {user.role}</span>
            </span>
            <button
              type="button"
              onClick={onLogout}
              style={{
                font: '500 11px var(--sans)',
                padding: '4px 10px',
                borderRadius: 5,
                border: '1px solid var(--border)',
                background: 'transparent',
                color: 'var(--fg-dim)',
                cursor: 'pointer',
              }}
            >
              Logout
            </button>
          </div>
        ) : null}
      </div>
    </header>
  );
}

function Pill({
  dot,
  label,
  value,
  pulse,
}: {
  dot: string;
  label: string;
  value: string;
  pulse?: boolean;
}) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '4px 9px',
        borderRadius: 999,
        background: 'var(--surface-2)',
        border: '1px solid var(--border-soft)',
        font: '500 10.5px var(--mono)',
      }}
    >
      <span
        className={pulse ? 'dot-pulse' : ''}
        style={{
          width: 6,
          height: 6,
          borderRadius: '50%',
          background: dot,
          boxShadow: pulse ? `0 0 6px ${dot}` : 'none',
          display: 'inline-block',
        }}
      />
      <span
        style={{
          color: 'var(--fg-faint)',
          letterSpacing: '0.1em',
          textTransform: 'uppercase',
        }}
      >
        {label}
      </span>
      <span
        className="tabular"
        style={{
          color: 'var(--fg-bright)',
          letterSpacing: '-0.005em',
        }}
      >
        {value}
      </span>
    </span>
  );
}
