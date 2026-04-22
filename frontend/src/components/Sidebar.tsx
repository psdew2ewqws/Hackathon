import { useEffect, useState } from 'react';
import { NavLink } from 'react-router-dom';
import styles from './Layout.module.css';

/**
 * Navigation sidebar — the app shell's left rail. Pulls a few live numbers
 * from /api/architecture so the operator sees at-a-glance health before
 * clicking into any tab. Badges are intentionally lightweight (counts only)
 * so the sidebar doesn't turn into a second dashboard.
 */

interface Badge {
  fps?: number;
  events?: number;
  incidents?: number;
  audit?: number;
  faults_active?: number;
  healthy?: boolean;
  generated_at?: string;
}

type IconProps = { className?: string };

const LiveIcon = ({ className }: IconProps) => (
  <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor">
    <rect x="2" y="3" width="12" height="9" rx="1.5" />
    <path d="M6 12v1.5M10 12v1.5M5 13.5h6" strokeLinecap="round" />
    <circle cx="5.5" cy="7.5" r="1.2" fill="currentColor" stroke="none" />
    <path d="M9 6l2.5 1.5L9 9z" fill="currentColor" stroke="none" />
  </svg>
);

const IncidentIcon = ({ className }: IconProps) => (
  <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round">
    <path d="M8 2.5l6 10.5H2z" />
    <path d="M8 7v2.5" />
    <circle cx="8" cy="11.5" r="0.5" fill="currentColor" stroke="none" />
  </svg>
);

const ArchIcon = ({ className }: IconProps) => (
  <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round">
    <rect x="2" y="2.5" width="5" height="4" rx="0.5" />
    <rect x="9" y="2.5" width="5" height="4" rx="0.5" />
    <rect x="2" y="9.5" width="5" height="4" rx="0.5" />
    <rect x="9" y="9.5" width="5" height="4" rx="0.5" />
    <path d="M7 4.5h2M7 11.5h2M4.5 6.5v3M11.5 6.5v3" />
  </svg>
);

const AuditIcon = ({ className }: IconProps) => (
  <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round">
    <path d="M3 2.5h7l3 3V13.5a1 1 0 01-1 1H3a1 1 0 01-1-1v-10a1 1 0 011-1z" />
    <path d="M10 2.5V5.5h3M5 8.5h6M5 11h6M5 6h2" />
  </svg>
);

const ChartIcon = ({ className }: IconProps) => (
  <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round">
    <path d="M2 13.5V2.5M2 13.5h12" />
    <path d="M5 10.5V8M8 10.5V5.5M11 10.5V7" />
  </svg>
);

export function Sidebar() {
  const [badge, setBadge] = useState<Badge>({});

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const [archRes, auditRes] = await Promise.all([
          fetch('/api/architecture'),
          fetch('/api/audit?n=1'),
        ]);
        if (!archRes.ok) throw new Error(`arch ${archRes.status}`);
        const arch = await archRes.json();
        const audit = auditRes.ok ? await auditRes.json() : null;

        const yolo = (arch.modules ?? []).find(
          (m: { id: string }) => m.id === 'yolo',
        );
        const incidentsRow = (arch.storage ?? []).find(
          (s: { name: string }) => s.name === 'Incident snapshots',
        );
        const eventsRow = (arch.storage ?? []).find(
          (s: { name: string }) => s.name === 'Live AI events',
        );

        if (!cancelled) {
          setBadge({
            fps: yolo?.fps,
            events: eventsRow?.size_bytes,
            incidents: incidentsRow?.size_bytes,
            audit: audit?.count,
            faults_active: (arch.faults ?? []).filter(
              (f: { active: boolean }) => f.active,
            ).length,
            healthy: yolo?.status === 'up',
            generated_at: arch.generated_at,
          });
        }
      } catch {
        if (!cancelled) setBadge((b) => ({ ...b, healthy: false }));
      }
    };
    tick();
    const id = window.setInterval(tick, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  const fpsLabel = badge.fps != null ? `${badge.fps.toFixed(1)} fps` : '—';

  return (
    <aside className={styles.sidebar}>
      <div className={styles.brand}>
        <div className={styles.brandLogo} aria-hidden="true" />
        <div>
          <div className={styles.brandTitle}>Traffic Ops</div>
          <div className={styles.brandSite}>SITE-001 · AMMAN</div>
        </div>
      </div>

      <div className={styles.liveBar}>
        <span
          className={`${styles.liveDot} ${!badge.healthy ? styles.liveDotOff : ''}`}
        />
        <span className={styles.liveLabel}>
          {badge.healthy ? 'LIVE' : 'OFFLINE'}
        </span>
        <span className={styles.liveStat}>{fpsLabel}</span>
      </div>

      <div className={styles.navGroup}>
        <div className={styles.navGroupLabel}>Operations</div>
        <ul className={styles.navList}>
          <li className={styles.navItem}>
            <NavLink
              to="/"
              end
              className={({ isActive }) =>
                `${styles.navLink} ${isActive ? styles.navLinkActive : ''}`
              }
            >
              <LiveIcon className={styles.navIcon} />
              Live Feed
              <span className={styles.navBadge}>{fpsLabel}</span>
            </NavLink>
          </li>
          <li className={styles.navItem}>
            <NavLink
              to="/incidents"
              className={({ isActive }) =>
                `${styles.navLink} ${isActive ? styles.navLinkActive : ''}`
              }
            >
              <IncidentIcon className={styles.navIcon} />
              Incidents
            </NavLink>
          </li>
        </ul>
      </div>

      <div className={styles.navGroup}>
        <div className={styles.navGroupLabel}>Analytics</div>
        <ul className={styles.navList}>
          <li className={styles.navItem}>
            <NavLink
              to="/analysis"
              className={({ isActive }) =>
                `${styles.navLink} ${isActive ? styles.navLinkActive : ''}`
              }
            >
              <ChartIcon className={styles.navIcon} />
              Analysis
              {badge.events != null && (
                <span className={styles.navBadge}>
                  {Math.round(badge.events / 1024 / 1024)}M
                </span>
              )}
            </NavLink>
          </li>
        </ul>
      </div>

      <div className={styles.navGroup}>
        <div className={styles.navGroupLabel}>System</div>
        <ul className={styles.navList}>
          <li className={styles.navItem}>
            <NavLink
              to="/system"
              className={({ isActive }) =>
                `${styles.navLink} ${isActive ? styles.navLinkActive : ''}`
              }
            >
              <ArchIcon className={styles.navIcon} />
              Architecture
              {badge.faults_active! > 0 && (
                <span
                  className={styles.navBadge}
                  style={{
                    color: 'var(--warn)',
                    borderColor: 'rgba(214,143,107,0.4)',
                  }}
                >
                  {badge.faults_active}
                </span>
              )}
            </NavLink>
          </li>
          <li className={styles.navItem}>
            <NavLink
              to="/audit"
              className={({ isActive }) =>
                `${styles.navLink} ${isActive ? styles.navLinkActive : ''}`
              }
            >
              <AuditIcon className={styles.navIcon} />
              Audit Log
            </NavLink>
          </li>
        </ul>
      </div>

      <div className={styles.sidebarFooter}>
        <div className={styles.version}>traffic-intel · v0.1.0</div>
        <time>
          {badge.generated_at
            ? new Date(badge.generated_at).toLocaleTimeString([], {
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
              })
            : '—'}
        </time>
      </div>
    </aside>
  );
}
