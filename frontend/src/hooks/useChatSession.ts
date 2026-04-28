import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  getLLMStatus,
  listLLMConversations,
  getLLMConversation,
  deleteLLMConversation,
  streamLLMChat,
  type LLMContentBlock,
  type LLMConversationSummary,
  type LLMStatus,
  type LLMStreamEvent,
} from '../api/llm';

export type ChatRole = 'user' | 'assistant';

export interface ChatToolCall {
  tool_use_id: string;
  name: string;
  args: unknown;
  ok: boolean | null;
}

export interface ChatMessage {
  id: string;          // local UI id; not the DB id
  role: ChatRole;
  text: string;
  tool_calls: ChatToolCall[];
  pending: boolean;
}

export type ChatPhase = 'idle' | 'streaming' | 'error';

export interface UseChatSession {
  status: LLMStatus | null;
  loadingStatus: boolean;
  conversations: LLMConversationSummary[];
  loadingConversations: boolean;
  refreshConversations: () => Promise<void>;
  conversationId: string | null;
  messages: ChatMessage[];
  phase: ChatPhase;
  errorMessage: string | null;
  send: (text: string) => Promise<void>;
  loadConversation: (id: string) => Promise<void>;
  newConversation: () => void;
  deleteConversation: (id: string) => Promise<void>;
}

function blockToText(content: string | LLMContentBlock[]): {
  text: string;
  tool_calls: ChatToolCall[];
} {
  if (typeof content === 'string') return { text: content, tool_calls: [] };
  let text = '';
  const tool_calls: ChatToolCall[] = [];
  for (const block of content) {
    if (block.type === 'text' && block.text) text += block.text;
    if (block.type === 'tool_use' && block.id && block.name) {
      tool_calls.push({
        tool_use_id: block.id,
        name: block.name,
        args: block.input ?? {},
        ok: null,
      });
    }
  }
  return { text, tool_calls };
}

function localId(): string {
  return `m_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

export function useChatSession(): UseChatSession {
  const [status, setStatus] = useState<LLMStatus | null>(null);
  const [loadingStatus, setLoadingStatus] = useState<boolean>(true);
  const [conversations, setConversations] = useState<LLMConversationSummary[]>([]);
  const [loadingConversations, setLoadingConversations] = useState<boolean>(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [phase, setPhase] = useState<ChatPhase>('idle');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const s = await getLLMStatus();
        if (!cancelled) setStatus(s);
      } catch (e) {
        if (!cancelled) setStatus(null);
      } finally {
        if (!cancelled) setLoadingStatus(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const refreshConversations = useCallback(async () => {
    setLoadingConversations(true);
    try {
      const list = await listLLMConversations();
      setConversations(list);
    } catch {
      setConversations([]);
    } finally {
      setLoadingConversations(false);
    }
  }, []);

  useEffect(() => {
    if (status?.configured) {
      void refreshConversations();
    }
  }, [status?.configured, refreshConversations]);

  const newConversation = useCallback(() => {
    abortRef.current?.abort();
    setConversationId(null);
    setMessages([]);
    setPhase('idle');
    setErrorMessage(null);
  }, []);

  const loadConversation = useCallback(async (id: string) => {
    abortRef.current?.abort();
    setPhase('idle');
    setErrorMessage(null);
    try {
      const detail = await getLLMConversation(id);
      const ui: ChatMessage[] = detail.messages.map((m) => {
        const { text, tool_calls } = blockToText(m.content);
        return {
          id: localId(),
          role: m.role,
          text,
          tool_calls,
          pending: false,
        };
      });
      setConversationId(id);
      setMessages(ui);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setErrorMessage(`failed to load conversation: ${msg}`);
    }
  }, []);

  const deleteConversation = useCallback(
    async (id: string) => {
      try {
        await deleteLLMConversation(id);
        if (id === conversationId) newConversation();
        await refreshConversations();
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        setErrorMessage(`failed to delete conversation: ${msg}`);
      }
    },
    [conversationId, newConversation, refreshConversations],
  );

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      if (!status?.configured) {
        setErrorMessage('LLM advisor is not configured.');
        return;
      }
      setErrorMessage(null);
      setPhase('streaming');

      const userMsg: ChatMessage = {
        id: localId(),
        role: 'user',
        text: trimmed,
        tool_calls: [],
        pending: false,
      };
      const assistantMsg: ChatMessage = {
        id: localId(),
        role: 'assistant',
        text: '',
        tool_calls: [],
        pending: true,
      };
      setMessages((prev) => [...prev, userMsg, assistantMsg]);

      abortRef.current?.abort();
      const ctl = new AbortController();
      abortRef.current = ctl;

      const updateAssistant = (mut: (m: ChatMessage) => ChatMessage) => {
        setMessages((prev) =>
          prev.map((m) => (m.id === assistantMsg.id ? mut(m) : m)),
        );
      };

      try {
        const status_code = await streamLLMChat({
          message: trimmed,
          conversation_id: conversationId,
          signal: ctl.signal,
          onEvent: (ev: LLMStreamEvent) => {
            if (ev.type === 'conversation') {
              setConversationId(ev.conversation_id);
            } else if (ev.type === 'text_delta') {
              updateAssistant((m) => ({ ...m, text: m.text + ev.text }));
            } else if (ev.type === 'tool_use') {
              updateAssistant((m) => ({
                ...m,
                tool_calls: [
                  ...m.tool_calls,
                  {
                    tool_use_id: ev.tool_use_id,
                    name: ev.name,
                    args: ev.args,
                    ok: null,
                  },
                ],
              }));
            } else if (ev.type === 'tool_result') {
              updateAssistant((m) => ({
                ...m,
                tool_calls: m.tool_calls.map((t) =>
                  t.tool_use_id === ev.tool_use_id ? { ...t, ok: ev.ok } : t,
                ),
              }));
            } else if (ev.type === 'turn_done') {
              updateAssistant((m) => ({ ...m, pending: false }));
              setPhase('idle');
              void refreshConversations();
            } else if (ev.type === 'error') {
              setErrorMessage(ev.message);
              updateAssistant((m) => ({ ...m, pending: false }));
              setPhase('error');
            }
          },
        });
        if (status_code === 503) {
          setErrorMessage('LLM advisor returned 503 — feature not configured.');
          updateAssistant((m) => ({ ...m, pending: false }));
          setPhase('error');
          // refresh status so the UI flips back to "not configured"
          try {
            setStatus(await getLLMStatus());
          } catch {
            /* keep prior status */
          }
        } else if (status_code !== 200) {
          setErrorMessage(`server returned ${status_code}`);
          updateAssistant((m) => ({ ...m, pending: false }));
          setPhase('error');
        }
      } catch (e: unknown) {
        if ((e as { name?: string }).name === 'AbortError') {
          updateAssistant((m) => ({ ...m, pending: false }));
          setPhase('idle');
          return;
        }
        const msg = e instanceof Error ? e.message : String(e);
        setErrorMessage(msg);
        updateAssistant((m) => ({ ...m, pending: false }));
        setPhase('error');
      }
    },
    [status?.configured, conversationId, refreshConversations],
  );

  return useMemo(
    () => ({
      status,
      loadingStatus,
      conversations,
      loadingConversations,
      refreshConversations,
      conversationId,
      messages,
      phase,
      errorMessage,
      send,
      loadConversation,
      newConversation,
      deleteConversation,
    }),
    [
      status,
      loadingStatus,
      conversations,
      loadingConversations,
      refreshConversations,
      conversationId,
      messages,
      phase,
      errorMessage,
      send,
      loadConversation,
      newConversation,
      deleteConversation,
    ],
  );
}
