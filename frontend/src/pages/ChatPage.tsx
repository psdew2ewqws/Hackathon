import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { useAuth } from '../auth/AuthContext';
import { useChatSession } from '../hooks/useChatSession';

export function ChatPage() {
  const { user } = useAuth();
  const session = useChatSession();
  const [draft, setDraft] = useState('');
  const bodyRef = useRef<HTMLDivElement | null>(null);

  // Scroll to bottom whenever messages or streaming phase changes.
  useEffect(() => {
    if (bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    }
  }, [session.messages, session.phase]);

  const role = user?.role ?? 'viewer';
  const operatorOrAbove = role === 'operator' || role === 'admin';
  const configured = !!session.status?.configured;
  const canSend = operatorOrAbove && configured && session.phase !== 'streaming';

  const onSend = async () => {
    const text = draft.trim();
    if (!text || !canSend) return;
    setDraft('');
    await session.send(text);
  };

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void onSend();
    }
  };

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '260px 1fr',
        height: 'calc(100vh - 60px)',
        gap: 1,
        background: '#0b0f14',
        color: '#e6edf3',
      }}
    >
      {/* ─── Left rail: conversations ─────────────────────────────────── */}
      <aside
        style={{
          background: '#0f172a',
          borderRight: '1px solid #1e293b',
          padding: 12,
          overflowY: 'auto',
          display: 'flex',
          flexDirection: 'column',
          gap: 6,
        }}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 6,
          }}
        >
          <span style={labelStyle}>Conversations</span>
          <button
            type="button"
            onClick={session.newConversation}
            disabled={!configured}
            style={btnSm('#22c55e')}
            title="New conversation"
          >
            + New
          </button>
        </div>

        {!configured && (
          <div style={{ fontSize: 11, opacity: 0.6 }}>
            LLM not configured — set ANTHROPIC_API_KEY and install the `llm` extra.
          </div>
        )}
        {!operatorOrAbove && (
          <div style={{ fontSize: 11, opacity: 0.6 }}>
            Operator role required to send messages. You can still view past chats.
          </div>
        )}

        {session.loadingConversations && (
          <div style={{ fontSize: 12, opacity: 0.6 }}>loading…</div>
        )}
        {session.conversations.map((c) => {
          const active = c.id === session.conversationId;
          return (
            <div
              key={c.id}
              onClick={() => void session.loadConversation(c.id)}
              style={{
                background: active ? '#1e293b' : 'transparent',
                border: `1px solid ${active ? '#3b82f6' : '#1e293b'}`,
                borderRadius: 6,
                padding: 8,
                cursor: 'pointer',
                fontSize: 12,
                display: 'flex',
                flexDirection: 'column',
                gap: 2,
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'flex-start',
                  gap: 6,
                }}
              >
                <strong
                  style={{
                    fontSize: 12,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    flex: 1,
                  }}
                  title={c.title || c.id}
                >
                  {c.title || `Chat ${c.id.slice(0, 8)}`}
                </strong>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    if (window.confirm('Delete this conversation?')) {
                      void session.deleteConversation(c.id);
                    }
                  }}
                  style={{
                    background: 'transparent',
                    color: '#f87171',
                    border: 'none',
                    cursor: 'pointer',
                    fontSize: 14,
                    padding: 0,
                  }}
                  title="Delete"
                >
                  ×
                </button>
              </div>
              <span style={{ opacity: 0.55 }}>
                {new Date(c.updated_at).toLocaleString()}
              </span>
              <span style={{ opacity: 0.55, fontSize: 10 }}>
                {(c.total_tokens_in ?? 0) + (c.total_tokens_out ?? 0)} tokens
              </span>
            </div>
          );
        })}

        {session.conversations.length === 0 && !session.loadingConversations && (
          <div style={{ fontSize: 12, opacity: 0.5 }}>No conversations yet.</div>
        )}
      </aside>

      {/* ─── Main: messages + composer ─────────────────────────────────── */}
      <section
        style={{
          display: 'grid',
          gridTemplateRows: 'auto 1fr auto',
          height: '100%',
        }}
      >
        <header
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            padding: '10px 14px',
            background: '#0f172a',
            borderBottom: '1px solid #1e293b',
          }}
        >
          <div>
            <div style={{ fontWeight: 700 }}>Traffic Advisor</div>
            <div style={{ fontSize: 11, opacity: 0.6 }}>
              {session.status?.model ?? 'claude-sonnet-4-6'} ·{' '}
              tools served via in-process dispatch (and via{' '}
              <code style={{ fontSize: 10 }}>python -m traffic_intel_mcp</code> for
              external MCP clients)
            </div>
          </div>
          <span style={{ fontSize: 11, opacity: 0.6 }}>
            {session.messages.length} messages
          </span>
        </header>

        <div
          ref={bodyRef}
          style={{
            overflowY: 'auto',
            padding: 16,
            display: 'flex',
            flexDirection: 'column',
            gap: 10,
          }}
        >
          {session.messages.length === 0 && (
            <div style={{ opacity: 0.5, fontSize: 13 }}>
              Ask about live state, recent incidents, signal recommendations, or
              run a custom SQL query against the persisted data. Try:{' '}
              <em>"show me the last 10 incidents"</em> or{' '}
              <em>"what's the current intersection state?"</em>
            </div>
          )}

          {session.messages.map((m) => (
            <MessageBubble key={m.id} message={m} />
          ))}

          {session.phase === 'streaming' && (
            <div style={{ opacity: 0.6, fontSize: 12 }}>streaming…</div>
          )}
          {session.errorMessage && (
            <div
              style={{
                background: '#7f1d1d',
                color: '#fff',
                padding: 10,
                borderRadius: 8,
                fontSize: 12,
              }}
            >
              {session.errorMessage}
            </div>
          )}
        </div>

        <footer
          style={{
            display: 'flex',
            gap: 8,
            padding: 12,
            background: '#0f172a',
            borderTop: '1px solid #1e293b',
          }}
        >
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKey}
            placeholder={
              !configured
                ? 'LLM not configured'
                : !operatorOrAbove
                ? 'Operator role required'
                : 'Ask the traffic advisor…  (Enter to send, Shift+Enter for newline)'
            }
            disabled={!canSend}
            rows={2}
            style={{
              flex: 1,
              background: '#0b0f14',
              color: '#e6edf3',
              border: '1px solid #1e293b',
              borderRadius: 8,
              padding: 10,
              fontSize: 13,
              resize: 'vertical',
              fontFamily: 'inherit',
            }}
          />
          <button
            type="button"
            onClick={onSend}
            disabled={!canSend || draft.trim().length === 0}
            style={{
              ...btnSm('#3b82f6'),
              padding: '0 18px',
              fontSize: 14,
              minWidth: 80,
            }}
          >
            Send
          </button>
        </footer>
      </section>
    </div>
  );
}

interface MsgProps {
  message: {
    id: string;
    role: 'user' | 'assistant';
    text: string;
    tool_calls: { name: string; ok: boolean | null }[];
    pending: boolean;
  };
}

function MessageBubble({ message }: MsgProps) {
  const isUser = message.role === 'user';
  const bg = isUser ? '#1e3a5f' : '#1e293b';
  return (
    <div
      style={{
        background: bg,
        padding: 12,
        borderRadius: 8,
        maxWidth: '85%',
        alignSelf: isUser ? 'flex-end' : 'flex-start',
        fontSize: 13,
        lineHeight: 1.5,
      }}
    >
      <div style={{ opacity: 0.6, fontSize: 11, marginBottom: 4 }}>
        {isUser ? 'you' : 'advisor'}
        {message.pending ? ' …' : ''}
      </div>
      {isUser ? (
        <div style={{ whiteSpace: 'pre-wrap' }}>{message.text}</div>
      ) : (
        <div className="markdown-body">
          <ReactMarkdown>{message.text || ''}</ReactMarkdown>
        </div>
      )}
      {message.tool_calls.length > 0 && (
        <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
          {message.tool_calls.map((tc, i) => {
            const status =
              tc.ok === true ? '✓' : tc.ok === false ? '✗' : '…';
            const color =
              tc.ok === true ? '#22c55e' : tc.ok === false ? '#f87171' : '#94a3b8';
            return (
              <span
                key={i}
                style={{
                  background: '#0f172a',
                  border: `1px solid ${color}`,
                  borderRadius: 999,
                  padding: '2px 8px',
                  fontSize: 11,
                  color,
                }}
              >
                {tc.name} {status}
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}

const labelStyle: React.CSSProperties = {
  fontSize: 11,
  letterSpacing: 0.6,
  color: '#94a3b8',
  textTransform: 'uppercase',
  fontWeight: 600,
};

function btnSm(bg: string): React.CSSProperties {
  return {
    background: bg,
    color: '#0a0e15',
    border: 'none',
    borderRadius: 6,
    padding: '4px 10px',
    fontWeight: 600,
    cursor: 'pointer',
    fontSize: 11,
  };
}
