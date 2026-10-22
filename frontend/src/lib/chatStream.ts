// Server-Sent Events client for the assistant.
//
// Not EventSource: that only does GET and can't send an Authorization header,
// and the turn is a POST carrying the question. So this reads the response
// body as a stream and parses the SSE framing by hand, which is about twenty
// lines and avoids either putting the question in a query string or inventing
// a GET endpoint that mutates a conversation.
//
// The backend emits progress and tool events before the answer (see
// backend/app/api/chat.py) because the turn may run several database lookups
// before it has anything to say. Callers get those as they happen so the UI can
// show "Reading your at-risk customers…" instead of a spinner.

import { API_BASE, authHeaders, type ChatMessage } from "./api";

export interface ChatStreamHandlers {
  onStatus?: (message: string) => void;
  /** One tool finished. `summary` is owner-readable, e.g. "Read 12 at-risk
   * customers from your data" — shown as the citation for the answer. */
  onTool?: (tool: string, summary: string) => void;
  onMessage: (payload: {
    conversation_id: string;
    message: ChatMessage;
    drafted_campaign_id: string | null;
  }) => void;
  onError?: (detail: string) => void;
}

interface SseEvent {
  event: string;
  data: string;
}

/** Split a chunk of SSE text into complete events, returning any trailing
 * partial frame so the caller can prepend it to the next chunk. */
export function parseSseBuffer(buffer: string): { events: SseEvent[]; rest: string } {
  const events: SseEvent[] = [];
  // Frames are separated by a blank line. A trailing fragment with no blank
  // line yet is an incomplete frame and must be carried over.
  const parts = buffer.split("\n\n");
  const rest = parts.pop() ?? "";
  for (const part of parts) {
    let event = "message";
    const dataLines: string[] = [];
    for (const line of part.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
    }
    if (dataLines.length) events.push({ event, data: dataLines.join("\n") });
  }
  return { events, rest };
}

/** Ask the assistant, streaming progress. Resolves when the turn is finished.
 *
 * Never throws for an answer the server could produce: a failed turn arrives as
 * an `error` event so the UI can show it in the thread. It throws only when the
 * request itself couldn't be made, which the caller handles as a dead request.
 */
export async function streamChat(
  input: { message: string; conversationId?: string | null },
  handlers: ChatStreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({
      message: input.message,
      conversation_id: input.conversationId ?? null,
    }),
    signal,
  });

  if (!res.ok || !res.body) {
    // A 402/422/500 arrives as a normal JSON error body, not as SSE.
    let detail = `The assistant is unavailable (${res.status}).`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    handlers.onError?.(detail);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const { events, rest } = parseSseBuffer(buffer);
      buffer = rest;

      for (const { event, data } of events) {
        let payload: unknown;
        try {
          payload = JSON.parse(data);
        } catch {
          continue; // a malformed frame shouldn't kill the stream
        }
        if (event === "status") {
          handlers.onStatus?.((payload as { message?: string }).message ?? "");
        } else if (event === "tool") {
          const tool = payload as { tool?: string; summary?: string };
          handlers.onTool?.(tool.tool ?? "", tool.summary ?? "");
        } else if (event === "message") {
          handlers.onMessage(payload as Parameters<ChatStreamHandlers["onMessage"]>[0]);
        } else if (event === "error") {
          handlers.onError?.(
            (payload as { detail?: string }).detail ?? "Something went wrong."
          );
        }
      }
    }
  } finally {
    // Releasing the lock matters when the caller aborted mid-turn.
    reader.releaseLock();
  }
}
