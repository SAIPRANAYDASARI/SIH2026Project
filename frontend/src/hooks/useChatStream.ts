import { useCallback, useRef, useState } from "react";

import { listConversationMessages, postChat } from "@/lib/api";
import { parseSSEStream } from "@/lib/sse";
import type {
  Audience,
  ChatConversationEvent,
  ChatErrorEvent,
  ChatFinalEvent,
  ChatTokenEvent,
  Citation,
  Language,
} from "@/types/api";

export interface DisplayMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  isStreaming?: boolean;
  citations?: Citation[];
  invalidCitationMarkers?: number[];
  guardrailViolations?: string[];
  forcedRefusal?: boolean;
  /** The *server's* id for this message, from the `final` event. Distinct
   * from `id`, which stays client-generated so the citation panel's
   * "active message" tracking survives the streaming→final transition —
   * feedback has to be addressed to this one, not to `id`. */
  serverMessageId?: string;
  /** Conversation this message belongs to — needed alongside
   * `serverMessageId` to address the feedback endpoint. */
  serverConversationId?: string;
  latencyMs?: number;
}

interface UseChatStreamResult {
  messages: DisplayMessage[];
  conversationId: string | null;
  isStreaming: boolean;
  error: string | null;
  sendMessage: (text: string, audience: Audience, language?: Language) => Promise<void>;
  stop: () => void;
  /** Replace the visible thread with a previously-persisted one (history
   * sidebar), or clear it for a new conversation when passed `null`. */
  loadConversation: (conversationId: string | null) => Promise<void>;
  /** The last question asked, so the UI can offer a retry after a failure
   * without the user retyping it. */
  lastUserMessage: string | null;
}

/**
 * Drives POST /api/v1/chat's SSE stream and turns it into React state:
 * one optimistic user bubble plus an assistant bubble that fills in
 * token-by-token, then gets replaced with the guardrail-redacted
 * authoritative text and resolved citations once the `final` event
 * arrives (see `app.api.v1.chat` docstring on the backend — `token` text
 * is provisional, `final` is authoritative and can differ if a guardrail
 * redaction fired).
 */
export function useChatStream(): UseChatStreamResult {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUserMessage, setLastUserMessage] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const updateAssistantMessage = useCallback(
    (assistantId: string, patch: Partial<DisplayMessage>) => {
      setMessages((prev) => prev.map((m) => (m.id === assistantId ? { ...m, ...patch } : m)));
    },
    [],
  );

  const sendMessage = useCallback(
    async (text: string, audience: Audience, language: Language = "en") => {
      const trimmed = text.trim();
      if (!trimmed || isStreaming) return;

      setError(null);
      setLastUserMessage(trimmed);
      const assistantId = crypto.randomUUID();
      setMessages((prev) => [
        ...prev,
        { id: crypto.randomUUID(), role: "user", content: trimmed },
        { id: assistantId, role: "assistant", content: "", isStreaming: true },
      ]);
      setIsStreaming(true);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const response = await postChat(
          {
            conversation_id: conversationId,
            message: trimmed,
            audience,
            target_language: language,
          },
          controller.signal,
        );

        // Checked in postChat, but narrows the type for parseSSEStream below.
        if (!response.body) throw new Error("No response body from chat endpoint.");

        for await (const evt of parseSSEStream(response.body)) {
          if (evt.event === "conversation") {
            const data = JSON.parse(evt.data) as ChatConversationEvent;
            setConversationId(data.conversation_id);
          } else if (evt.event === "token") {
            const data = JSON.parse(evt.data) as ChatTokenEvent;
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId ? { ...m, content: m.content + data.text } : m,
              ),
            );
          } else if (evt.event === "final") {
            const data = JSON.parse(evt.data) as ChatFinalEvent;
            // Deliberately keeps the client-generated `assistantId` rather
            // than switching to `data.message_id` — the UI (App.tsx) tracks
            // "the active message" by this id from the moment the bubble
            // is created, and swapping it out here would break that
            // tracking exactly when citations become available.
            updateAssistantMessage(assistantId, {
              citations: data.citations,
              invalidCitationMarkers: data.invalid_citation_markers,
              guardrailViolations: data.guardrail_violations,
              forcedRefusal: data.forced_refusal,
              serverMessageId: data.message_id,
              serverConversationId: data.conversation_id,
              latencyMs: data.latency_ms,
              isStreaming: false,
            });
          } else if (evt.event === "error") {
            const data = JSON.parse(evt.data) as ChatErrorEvent;
            setError(data.detail);
            updateAssistantMessage(assistantId, { isStreaming: false });
          }
        }
      } catch (err) {
        if (controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
        updateAssistantMessage(assistantId, { isStreaming: false });
      } finally {
        setIsStreaming(false);
      }
    },
    [conversationId, isStreaming, updateAssistantMessage],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const loadConversation = useCallback(async (id: string | null) => {
    abortRef.current?.abort();
    setError(null);
    setLastUserMessage(null);

    if (id === null) {
      setMessages([]);
      setConversationId(null);
      return;
    }

    try {
      const history = await listConversationMessages(id);
      setMessages(
        history
          // System messages are an internal role; the transcript only ever
          // shows the two sides of the conversation.
          .filter((m) => m.role !== "system")
          .map((m) => ({
            id: m.id,
            role: m.role as "user" | "assistant",
            content: m.content,
            citations: m.citations ?? undefined,
            latencyMs: m.latency_ms ?? undefined,
            // Persisted history is addressable for feedback: the row's own
            // id is the server id, unlike a freshly-streamed message whose
            // `id` is client-generated.
            serverMessageId: m.id,
            serverConversationId: id,
          })),
      );
      setConversationId(id);
    } catch {
      setError("Couldn't load that conversation.");
    }
  }, []);

  return {
    messages,
    conversationId,
    isStreaming,
    error,
    sendMessage,
    stop,
    loadConversation,
    lastUserMessage,
  };
}
