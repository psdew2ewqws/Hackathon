import { NavLink, useNavigate } from 'react-router-dom';
import { roleAtLeast, useAuth, type Role } from '../auth/AuthContext';

interface NavItem {
  to: string;
  label: string;
  end?: boolean;
  minRole: Role;
}

const NAV_ITEMS: NavItem[] = [
  { to: '/', label: 'Live', end: true, minRole: 'viewer' },
  { to: '/signal', label: 'Signal', minRole: 'operator' },
  { to: '/signal-timing', label: 'Signal Timing', minRole: 'operator' },
  { to: '/forecast', label: 'Forecast', minRole: 'operator' },
  { to: '/incidents', label: 'Incidents', minRole: 'operator' },
  { to: '/history', label: 'History', minRole: 'operator' },
  { to: '/lanes', label: 'Lanes', minRole: 'operator' },
  { to: '/chat', label: 'Chat', minRole: 'operator' },
  { to: '/system', label: 'System', minRole: 'admin' },
  { to: '/audit', label: 'Audit', minRole: 'admin' },
];

export function Nav() {
  const { user, isAuthenticated, logout } = useAuth();
  const navigate = useNavigate();

  const visible = NAV_ITEMS.filter((item) => roleAtLeast(user?.role, item.minRole));

  const onLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  return (
    <nav
      style={{
        display: 'flex',
        gap: 4,
        padding: '10px 18px',
        background: '#121820',
        borderBottom: '1px solid #1e2630',
        alignItems: 'center',
      }}
    >
      <strong style={{ marginRight: 18, letterSpacing: '.02em' }}>
        Wadi Saqra · PoC
      </strong>
      {visible.map((l) => (
        <NavLink
          key={l.to}
          to={l.to}
          end={l.end}
          style={({ isActive }) => ({
            padding: '6px 12px',
            borderRadius: 6,
            fontSize: 13,
            color: isActive ? '#0b0f14' : '#e6edf3',
            background: isActive ? '#66ff88' : 'transparent',
            textDecoration: 'none',
            fontWeight: isActive ? 600 : 500,
          })}
        >
          {l.label}
        </NavLink>
      ))}

      <span style={{ flex: 1 }} />

      {isAuthenticated && user ? (
        <>
          <span
            style={{
              fontSize: 12,
              color: '#9097A0',
              marginRight: 10,
              fontFamily: 'ui-monospace, "JetBrains Mono", monospace',
            }}
          >
            {user.username}{' '}
            <span style={{ color: '#E8B464' }}>({user.role})</span>
          </span>
          <button
            type="button"
            onClick={onLogout}
            style={{
              padding: '5px 11px',
              fontSize: 12,
              color: '#e6edf3',
              background: 'transparent',
              border: '1px solid #1e2630',
              borderRadius: 6,
              cursor: 'pointer',
            }}
          >
            Logout
          </button>
        </>
      ) : null}
    </nav>
  );
}
