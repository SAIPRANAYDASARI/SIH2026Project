import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useChatStream } from "@/hooks/useChatStream";

function sseResponse(events: { event: string; data: unknown }[], ok = true): Response {
  const body = events.map((e) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`).join("");
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(body));
      controller.close();
    },
  });
  return new Response(stream, { status: ok ? 200 : 500 });
}

describe("useChatStream", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("streams tokens into the assistant message then applies the final event", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      sseResponse([
        { event: "conversation", data: { conversation_id: "conv-1" } },
        { event: "token", data: { text: "Hello " } },
        { event: "token", data: { text: "world [1]." } },
        {
          event: "final",
          data: {
            message_id: "msg-1",
            conversation_id: "conv-1",
            citations: [
              {
                marker: 1,
                chunk_id: "c1",
                is_number: "IS 15111",
                clause_number: "4.2.1",
                document_title: "IS 15111",
                document_source_url: null,
              },
            ],
            invalid_citation_markers: [],
            guardrail_violations: [],
            intent: "standard_lookup",
            model_backend: "ollama:llama3.1:8b",
            latency_ms: 42,
            forced_refusal: false,
          },
        },
      ]),
    );

    const { result } = renderHook(() => useChatStream());

    await act(async () => {
      await result.current.sendMessage("what is IS 15111?", "consumer");
    });

    await waitFor(() => expect(result.current.isStreaming).toBe(false));

    expect(result.current.conversationId).toBe("conv-1");
    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[0]).toMatchObject({
      role: "user",
      content: "what is IS 15111?",
    });
    expect(result.current.messages[1]).toMatchObject({
      role: "assistant",
      content: "Hello world [1].",
      isStreaming: false,
    });
    expect(result.current.messages[1]?.citations).toHaveLength(1);
    expect(result.current.error).toBeNull();
  });

  it("surfaces the error event without leaving the message stuck streaming", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      sseResponse([{ event: "error", data: { detail: "The answer engine failed." } }]),
    );

    const { result } = renderHook(() => useChatStream());

    await act(async () => {
      await result.current.sendMessage("hello", "consumer");
    });

    expect(result.current.error).toBe("The answer engine failed.");
    expect(result.current.messages[1]?.isStreaming).toBe(false);
  });

  it("ignores a blank message and never calls fetch", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const { result } = renderHook(() => useChatStream());

    await act(async () => {
      await result.current.sendMessage("   ", "consumer");
    });

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(result.current.messages).toHaveLength(0);
  });

  it("sets a generic error message when the request throws", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("network down"));

    const { result } = renderHook(() => useChatStream());

    await act(async () => {
      await result.current.sendMessage("hello", "consumer");
    });

    expect(result.current.error).toBe("network down");
    expect(result.current.messages[1]?.isStreaming).toBe(false);
  });
});
