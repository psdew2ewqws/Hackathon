import { useEffect, useRef, useState } from 'react';
import { useAuth } from '../../auth/AuthContext';
import { useChatSession } from '../../hooks/useChatSession';

const SUGGESTED: Array<{ label: string; prompt: string }> = [
  {
    label: 'east vs typical',
    prompt:
      'How does the East approach right now compare to the typical-day Google data for this hour? Use both get_current_state and get_typical_day_gmaps.',
  },
  {
    label: 'recommend timing',
    prompt:
      'What signal timing do you recommend for the next hour? Pull get_recommendation with scope=forecast and explain the green-time split.',
  },
  {
    label: 'incidents last 30m',
    prompt:
      'Anything notable in incidents in the last 30 minutes? Use list_incidents with since_iso = 30 minutes ago.',
  },
  {
    label: 'pm peak vs yesterday',
    prompt:
      "Compare today's PM peak demand (16:00–18:00) to yesterday's. Use get_history with bucket_minutes=60.",
  },
];

const TOOL_HUE: Record<string, string> = {
  get_current_state: 'var(--ai)',
  get_typical_day_gmaps: '#a78bfa',
  get_forecast: '#a78bfa',
  get_recommendation: 'var(--good)',
  list_incidents: 'var(--bad)',
  get_signal_plan: 'var(--accent)',
  get_history: 'var(--fg-dim)',
  query_sqlite: 'var(--fg-dim)',
};

export function AdvisorChatPanel() {
  const { isAuthenticated, user } = useAuth();
  const session = useChatSession();
  const [draft, setDraft] = useState('');
  const bodyRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    }
  }, [session.messages, session.phase]);

  const role = user?.role ?? 'viewer';
  const operatorOrAbove = role === 'operator' || role === 'admin';
  const configured = !!session.status?.configured;
  const canSend = isAuthenticated && operatorOrAbove && configured && session.phase !== 'streaming';

  const onSend = async (text?: string) => {
    const value = (text ?? draft).trim();
    if (!value || !canSend) return;
    setDraft('');
    await session.send(value);
  };

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void onSend();
    }
  };

  // Status pill in header
  const statusDot =
    session.phase === 'streaming'
      ? 'var(--ai)'
      : configured
      ? 'var(--good)'
      : 'var(--fg-faint)';

  return (
    <div
      style={{
        background: 'var(--surface-2)',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--r-md)',
        padding: '12px 14px 14px',
        display: 'flex',
        flexDirection: 'column',
        minHeight: 360,
      }}
    >
      {/* Header */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          marginBottom: 10,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
          <span
            style={{
              font: '600 11px var(--mono)',
              letterSpacing: '0.16em',
              textTransform: 'uppercase',
              color: 'var(--fg-bright)',
            }}
          >
            AI advisor
          </span>
          <span
            style={{
              font: '500 10px var(--mono)',
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              color: 'var(--fg-faint)',
            }}
          >
            {session.status?.model ?? 'claude · mcp'} · {session.status?.role_required ?? 'operator'}+
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              font: '500 10px var(--mono)',
              letterSpacing: '0.1em',
              textTransform: 'uppercase',
              color: statusDot,
            }}
          >
            <span
              className={session.phase === 'streaming' ? 'dot-pulse' : ''}
              style={{
                width: 6,
                height: 6,
                borderRadius: '50%',
                background: statusDot,
              }}
            />
            {session.phase === 'streaming' ? 'thinking' : configured ? 'ready' : 'offline'}
          </span>
          <button
            type="button"
            onClick={session.newConversation}
            disabled={!configured || session.phase === 'streaming'}
            style={{
              font: '500 10px var(--mono)',
              letterSpacing: '0.1em',
              textTransform: 'uppercase',
              color: 'var(--fg-dim)',
              background: 'transparent',
              border: '1px solid var(--border)',
              borderRadius: 5,
              padding: '3px 9px',
              cursor: 'pointer',
            }}
          >
            new
          </button>
        </div>
      </div>

      {/* Messages */}
      <div
        ref={bodyRef}
        className="scroll-thin"
        style={{
          flex: 1,
          minHeight: 180,
          maxHeight: 380,
          overflowY: 'auto',
          padding: '4px 2px',
          display: 'flex',
          flexDirection: 'column',
          gap: 10,
        }}
      >
        {!configured && (
          <div
            style={{
              font: '500 11px var(--mono)',
              color: 'var(--warn)',
              padding: '12px 8px',
              border: '1px dashed var(--border)',
              borderRadius: 6,
            }}
          >
            {session.status?.api_key_set === false
              ? 'ANTHROPIC_API_KEY not set on the server. Advisor is offline; everything else still works.'
              : session.status?.sdk_installed === false
              ? 'Anthropic SDK not installed on the server.'
              : 'LLM advisor not configured.'}
          </div>
        )}

        {!operatorOrAbove && configured && (
          <div
            style={{
              font: '500 11px var(--mono)',
              color: 'var(--fg-faint)',
            }}
          >
            advisor requires operator role · current role: {role}
          </div>
        )}

        {session.messages.length === 0 && configured && operatorOrAbove && (
          <div
            style={{
              font: '500 11px var(--mono)',
              color: 'var(--fg-faint)',
              letterSpacing: '0.04em',
              padding: '4px 0 2px',
            }}
          >
            ask anything · the advisor calls 8 MCP tools to answer:
          </div>
        )}

        {session.messages.map((m) => (
          <div
            key={m.id}
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 4,
              alignItems: m.role === 'user' ? 'flex-end' : 'flex-start',
            }}
          >
            <div
              style={{
                font: '500 9px var(--mono)',
                letterSpacing: '0.18em',
                textTransform: 'uppercase',
                color: m.role === 'user' ? 'var(--accent)' : 'var(--ai)',
              }}
            >
              {m.role === 'user' ? user?.username ?? 'you' : 'advisor'}
            </div>
            <div
              style={{
                background: m.role === 'user' ? 'var(--accent-ghost)' : 'var(--surface)',
                border: '1px solid',
                borderColor: m.role === 'user' ? 'var(--accent-soft)' : 'var(--border-soft)',
                borderRadius: 8,
                padding: '8px 11px',
                maxWidth: '90%',
                font: '400 12.5px/1.55 var(--sans)',
                color: 'var(--fg)',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}
            >
              {m.text || (m.pending ? '…' : '')}
              {m.tool_calls.length > 0 && (
                <div
                  style={{
                    display: 'flex',
                    flexWrap: 'wrap',
                    gap: 4,
                    marginTop: 8,
                  }}
                >
                  {m.tool_calls.map((tc) => {
                    const hue = TOOL_HUE[tc.name] ?? 'var(--fg-dim)';
                    return (
                      <span
                        key={tc.tool_use_id}
                        title={`${tc.name}(${JSON.stringify(tc.args)})`}
                        style={{
                          font: '500 9.5px var(--mono)',
                          color: hue,
                          background: 'var(--surface-3)',
                          border: '1px solid var(--border-soft)',
                          borderLeft: `2px solid ${hue}`,
                          padding: '2px 7px',
                          borderRadius: 4,
                          letterSpacing: '0.02em',
                        }}
                      >
                        {tc.name}
                        {tc.ok === false && (
                          <span style={{ color: 'var(--bad)', marginLeft: 4 }}>!</span>
                        )}
                      </span>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        ))}

        {session.errorMessage && (
          <div
            style={{
              font: '500 11px var(--mono)',
              color: 'var(--bad)',
            }}
          >
            {session.errorMessage}
          </div>
        )}
      </div>

      {/* Suggestion chips */}
      {session.messages.length === 0 && canSend && (
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: 6,
            margin: '8px 0',
          }}
        >
          {SUGGESTED.map((s) => (
            <button
              key={s.label}
              type="button"
              onClick={() => void onSend(s.prompt)}
              style={{
                font: '500 10.5px var(--mono)',
                letterSpacing: '0.04em',
                color: 'var(--fg-dim)',
                background: 'var(--surface)',
                border: '1px solid var(--border-soft)',
                borderRadius: 999,
                padding: '4px 10px',
                cursor: 'pointer',
              }}
            >
              {s.label}
            </button>
          ))}
        </div>
      )}

      {/* Composer */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr auto',
          gap: 8,
          marginTop: 10,
        }}
      >
        <textarea
          rows={2}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKey}
          placeholder={
            canSend
              ? 'ask the advisor — it can call MCP tools to read live state, history, typical-day, recommendations'
              : !configured
              ? 'advisor offline'
              : !operatorOrAbove
              ? 'operator role required'
              : 'streaming…'
          }
          disabled={!canSend}
          style={{
            font: '400 12.5px var(--sans)',
            color: 'var(--fg)',
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 6,
            padding: '8px 10px',
            resize: 'vertical',
            minHeight: 38,
            outline: 'none',
          }}
        />
        <button
          type="button"
          onClick={() => void onSend()}
          disabled={!canSend || !draft.trim()}
          style={{
            font: '600 11px var(--mono)',
            letterSpacing: '0.1em',
            textTransform: 'uppercase',
            color: canSend && draft.trim() ? '#0a0a0a' : 'var(--fg-faint)',
            background:
              canSend && draft.trim() ? 'var(--accent)' : 'var(--surface-3)',
            border: '1px solid',
            borderColor: canSend && draft.trim() ? 'var(--accent)' : 'var(--border)',
            borderRadius: 6,
            padding: '0 16px',
            cursor: canSend && draft.trim() ? 'pointer' : 'not-allowed',
            minWidth: 80,
          }}
        >
          {session.phase === 'streaming' ? '…' : 'send'}
        </button>
      </div>
    </div>
  );
}
