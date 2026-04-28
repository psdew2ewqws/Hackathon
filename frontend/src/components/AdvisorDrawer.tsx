import { useEffect, useRef, useState } from 'react';
import { useAuth } from '../auth/AuthContext';
import { useChatSession } from '../hooks/useChatSession';
import styles from './AdvisorDrawer.module.css';

export function AdvisorDrawer() {
  const { isAuthenticated, user } = useAuth();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState('');
  const [showHistory, setShowHistory] = useState(false);
  const session = useChatSession();
  const bodyRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    }
  }, [session.messages, session.phase]);

  if (!isAuthenticated) return null;

  const onSend = async () => {
    const text = draft.trim();
    if (!text || session.phase === 'streaming') return;
    setDraft('');
    await session.send(text);
  };

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void onSend();
    }
  };

  const configured = !!session.status?.configured;
  const role = user?.role ?? 'viewer';
  const operatorOrAbove = role === 'operator' || role === 'admin';

  return (
    <>
      <button
        type="button"
        className={`${styles.toggle} ${open ? styles.toggleActive : ''}`}
        onClick={() => setOpen((v) => !v)}
        aria-label="Toggle traffic advisor"
        title="Traffic advisor"
      >
        {open ? '×' : '✶'}
      </button>

      <div
        className={`${styles.drawer} ${open ? styles.drawerOpen : ''}`}
        aria-hidden={!open}
      >
        <div className={styles.header}>
          <div className={styles.headerTitle}>Traffic Advisor</div>
          <div className={styles.headerSub}>
            {session.status?.model ?? 'claude-sonnet-4-6'}
          </div>
          <button
            type="button"
            className={styles.iconBtn}
            onClick={() => setShowHistory((v) => !v)}
            disabled={!configured}
            title="Conversation history"
          >
            ≡
          </button>
          <button
            type="button"
            className={styles.iconBtn}
            onClick={session.newConversation}
            disabled={!configured}
            title="New conversation"
          >
            +
          </button>
        </div>

        <div className={styles.body} ref={bodyRef}>
          {session.loadingStatus && (
            <div className={styles.empty}>checking advisor status…</div>
          )}

          {!session.loadingStatus && !configured && (
            <div className={styles.empty}>
              <div className={styles.emptyTitle}>LLM Advisor — opt-in</div>
              <div>
                The advisor is shipped as a <strong>feature</strong> that requires an
                Anthropic API key. With no key, no outbound calls happen and the
                §7.7 isolation contract holds by default.
              </div>
              <div style={{ marginTop: 10 }}>
                To activate (operator decision):
                <pre
                  style={{
                    background: '#0b0f14',
                    border: '1px solid #1e2630',
                    borderRadius: 6,
                    padding: 8,
                    fontSize: 11,
                    margin: '6px 0',
                  }}
                >{`pip install 'traffic-intel[llm]'
export ANTHROPIC_API_KEY=sk-ant-…`}</pre>
                When active, <code>api.anthropic.com</code> is the only allowlisted
                egress; calls are gated to <code>operator+</code> and audited.
              </div>
              <div className={styles.emptyMeta}>
                sdk_installed={String(session.status?.sdk_installed ?? false)} ·
                api_key_set={String(session.status?.api_key_set ?? false)} ·
                role={role}
              </div>
            </div>
          )}

          {!session.loadingStatus && configured && !operatorOrAbove && (
            <div className={styles.empty}>
              <div className={styles.emptyTitle}>Operator role required</div>
              <div>
                Your account is <code>{role}</code>. The advisor is gated to
                <code> operator </code> or above, the same tier as the ingest
                endpoints. Ask an admin if you need access.
              </div>
            </div>
          )}

          {configured && operatorOrAbove && session.messages.length === 0 && (
            <div className={styles.empty}>
              <div className={styles.emptyTitle}>Ask anything about Wadi Saqra</div>
              <div>
                The advisor grounds every answer in tool calls against the live
                detector counts, forecast, recommendation, and incident log.
              </div>
              <div style={{ marginTop: 8, opacity: 0.8 }}>
                Try: <em>"What's congesting E?"</em> ·{' '}
                <em>"Compare this hour to yesterday"</em> ·{' '}
                <em>"What should I do about the wrong-way spike?"</em>
              </div>
            </div>
          )}

          {session.messages.map((m) => (
            <div
              key={m.id}
              className={`${styles.message} ${
                m.role === 'user' ? styles.messageUser : styles.messageAssistant
              }`}
            >
              <div className={styles.messageRole}>
                {m.role === 'user' ? user?.username ?? 'you' : 'advisor'}
              </div>
              <div>
                {m.text}
                {m.role === 'assistant' && m.pending && (
                  <span className={styles.cursor} aria-hidden />
                )}
              </div>
              {m.tool_calls.length > 0 && (
                <div className={styles.toolStrip}>
                  {m.tool_calls.map((t) => (
                    <span
                      key={t.tool_use_id}
                      className={`${styles.toolChip} ${
                        t.ok === true
                          ? styles.toolChipOk
                          : t.ok === false
                          ? styles.toolChipErr
                          : ''
                      }`}
                      title={JSON.stringify(t.args)}
                    >
                      {t.name}
                      {t.ok === null ? '…' : t.ok ? ' ✓' : ' ✗'}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}

          {session.errorMessage && (
            <div className={styles.error}>{session.errorMessage}</div>
          )}
        </div>

        {showHistory && configured && (
          <div className={styles.history}>
            {session.loadingConversations && <div>loading…</div>}
            {!session.loadingConversations && session.conversations.length === 0 && (
              <div>no conversations yet</div>
            )}
            {session.conversations.map((c) => (
              <div key={c.id} className={styles.historyItem}>
                <span
                  className={styles.historyTitle}
                  onClick={() => {
                    setShowHistory(false);
                    void session.loadConversation(c.id);
                  }}
                >
                  {c.title || c.id.slice(0, 12)}
                </span>
                <button
                  type="button"
                  className={styles.iconBtn}
                  onClick={() => void session.deleteConversation(c.id)}
                  title="Delete conversation"
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        )}

        <div className={styles.composer}>
          <textarea
            className={styles.textarea}
            placeholder={
              configured && operatorOrAbove
                ? 'Ask about the intersection, the forecast, or the signal plan…'
                : 'Disabled — see message above'
            }
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKey}
            disabled={!configured || !operatorOrAbove || session.phase === 'streaming'}
          />
          <div className={styles.composerRow}>
            <span>
              {session.phase === 'streaming'
                ? 'streaming…'
                : session.phase === 'error'
                ? 'error — try again'
                : 'enter to send · shift+enter for newline'}
            </span>
            <button
              type="button"
              className={styles.send}
              onClick={() => void onSend()}
              disabled={
                !configured ||
                !operatorOrAbove ||
                session.phase === 'streaming' ||
                draft.trim().length === 0
              }
            >
              Send
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
