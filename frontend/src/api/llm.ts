// Typed client for the LLM advisor endpoints. SSE is consumed via fetch
// (not EventSource) so the AuthContext fetch interceptor injects the JWT
// like every other /api/* call.

import { apiUrl } from './client';

export interface LLMStatus {
  configured: boolean;
  sdk_installed: boolean;
  api_key_set: boolean;
  model: string;
  max_tokens: number;
  role_required: 'operator';
  egress: string | null;
}

export interface LLMConversationSummary {
  id: string;
  user_id: number;
  username: string;
  title: string | null;
  model: string;
  created_at: string;
  updated_at: string;
  total_tokens_in: number;
  total_tokens_out: number;
}

export type LLMMessageContent = string | LLMContentBlock[];

export interface LLMContentBlock {
  type: 'text' | 'tool_use' | 'tool_result';
  text?: string;
  id?: string;
  name?: string;
  input?: unknown;
  tool_use_id?: string;
  content?: unknown;
  is_error?: boolean;
}

export interface LLMConversationDetail extends LLMConversationSummary {
  site_id: string | null;
  messages: Array<{
    turn_index: number;
    ts: string;
    role: 'user' | 'assistant';
    content: LLMMessageContent;
    tokens_in: number | null;
    tokens_out: number | null;
  }>;
}

export type LLMStreamEvent =
  | { type: 'conversation'; conversation_id: string }
  | { type: 'text_delta'; text: string }
  | { type: 'tool_use'; tool_use_id: string; name: string; args: unknown }
  | { type: 'tool_result'; tool_use_id: string; ok: boolean }
  | {
      type: 'turn_done';
      stop_reason: string | null;
      tokens_in: number;
      tokens_out: number;
    }
  | { type: 'error'; message: string };

export async function getLLMStatus(signal?: AbortSignal): Promise<LLMStatus> {
  const r = await fetch(apiUrl('/api/llm/status'), { signal });
  if (!r.ok) throw new Error(`/api/llm/status: ${r.status}`);
  return (await r.json()) as LLMStatus;
}

export async function listLLMConversations(
  signal?: AbortSignal,
): Promise<LLMConversationSummary[]> {
  const r = await fetch(apiUrl('/api/llm/conversations?limit=20'), { signal });
  if (!r.ok) throw new Error(`/api/llm/conversations: ${r.status}`);
  const j = (await r.json()) as { conversations: LLMConversationSummary[] };
  return j.conversations;
}

export async function getLLMConversation(
  id: string,
  signal?: AbortSignal,
): Promise<LLMConversationDetail> {
  const r = await fetch(apiUrl(`/api/llm/conversations/${encodeURIComponent(id)}`), {
    signal,
  });
  if (!r.ok) throw new Error(`/api/llm/conversations/${id}: ${r.status}`);
  return (await r.json()) as LLMConversationDetail;
}

export async function deleteLLMConversation(id: string): Promise<void> {
  const r = await fetch(apiUrl(`/api/llm/conversations/${encodeURIComponent(id)}`), {
    method: 'DELETE',
  });
  if (!r.ok) throw new Error(`delete /api/llm/conversations/${id}: ${r.status}`);
}

export interface ChatStreamArgs {
  message: string;
  conversation_id?: string | null;
  signal?: AbortSignal;
  onEvent: (ev: LLMStreamEvent) => void;
}

/**
 * Open an SSE stream against POST /api/llm/chat. The AuthContext fetch
 * interceptor adds the Bearer token; we read the stream in chunks and
 * dispatch each `data: {...}` line as a typed event.
 *
 * Returns the HTTP status — 503 means the feature is not configured;
 * 200 means the stream completed successfully (the final event will be
 * either `turn_done` or `error`).
 */
export async function streamLLMChat({
  message,
  conversation_id,
  signal,
  onEvent,
}: ChatStreamArgs): Promise<number> {
  const r = await fetch(apiUrl('/api/llm/chat'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ message, conversation_id }),
    signal,
  });
  if (!r.ok || !r.body) {
    return r.status;
  }
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const frame = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const line = frame.split('\n').find((l) => l.startsWith('data: '));
      if (!line) continue;
      try {
        const ev = JSON.parse(line.slice(6)) as LLMStreamEvent;
        onEvent(ev);
      } catch {
        // ignore malformed events
      }
    }
  }
  return r.status;
}
