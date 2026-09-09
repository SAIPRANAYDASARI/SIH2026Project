import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "@/App";
import * as api from "@/lib/api";

function renderWithClient(): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function sseResponse(events: { event: string; data: unknown }[]): Response {
  const body = events.map((e) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`).join("");
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(body));
      controller.close();
    },
  });
  return new Response(stream, { status: 200 });
}

describe("App", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows an online badge once the health check succeeds", async () => {
    vi.spyOn(api, "getHealth").mockResolvedValue({
      status: "ok",
      database: "ok",
      redis: "ok",
      app_env: "development",
      llm_backend: "ollama",
    });

    renderWithClient();

    await waitFor(() => expect(screen.getByText("online")).toBeInTheDocument());
  });

  it("shows a degraded badge when a dependency is unreachable", async () => {
    vi.spyOn(api, "getHealth").mockResolvedValue({
      status: "ok",
      database: "ok",
      redis: "unreachable",
      app_env: "development",
      llm_backend: "ollama",
    });

    renderWithClient();

    await waitFor(() => expect(screen.getByText("degraded")).toBeInTheDocument());
  });

  it("shows an unreachable badge when the backend can't be reached at all", async () => {
    vi.spyOn(api, "getHealth").mockRejectedValue(new Error("network error"));

    renderWithClient();

    await waitFor(() => expect(screen.getByText("backend unreachable")).toBeInTheDocument());
  });

  it("shows the empty-state prompt before any message is sent", () => {
    vi.spyOn(api, "getHealth").mockResolvedValue({
      status: "ok",
      database: "ok",
      redis: "ok",
      app_env: "development",
      llm_backend: "ollama",
    });

    renderWithClient();

    expect(screen.getByText(/ask about indian standards/i)).toBeInTheDocument();
  });

  it("sends a message, streams the answer, and shows its citation in the panel", async () => {
    vi.spyOn(api, "getHealth").mockResolvedValue({
      status: "ok",
      database: "ok",
      redis: "ok",
      app_env: "development",
      llm_backend: "ollama",
    });
    // Routed per-URL, and building a *fresh* Response each call: a
    // Response body can only be consumed once, so a single shared instance
    // would be drained by whichever request fired first (the history
    // sidebar's `GET /conversations` beats the chat POST).
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/conversations")) {
        return Promise.resolve(new Response("[]", { status: 200 }));
      }
      return Promise.resolve(
        sseResponse([
          { event: "conversation", data: { conversation_id: "conv-1" } },
          { event: "token", data: { text: "LED drivers are covered by IS 15111 [1]." } },
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
                  document_title: "IS 15111 LED Luminaires",
                  document_source_url: "https://example.com/is-15111",
                },
              ],
              invalid_citation_markers: [],
              guardrail_violations: [],
              intent: "product_to_standard",
              model_backend: "ollama:llama3.1:8b",
              latency_ms: 88,
              forced_refusal: false,
            },
          },
        ]),
      );
    });

    renderWithClient();
    const user = userEvent.setup();

    await user.type(
      screen.getByLabelText("Message", { exact: true }),
      "which standard covers LED drivers?",
    );
    await user.click(screen.getByLabelText(/send message/i));

    await waitFor(() =>
      expect(screen.getByText(/LED drivers are covered by IS 15111/)).toBeInTheDocument(),
    );

    // The citation panel auto-follows the newest assistant message.
    await waitFor(() => expect(screen.getByText("IS 15111 LED Luminaires")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /view source/i })).toHaveAttribute(
      "href",
      "https://example.com/is-15111",
    );
  });
});
