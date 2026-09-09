import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MessageActions } from "@/components/chat/MessageActions";
import * as api from "@/lib/api";
import type { DisplayMessage } from "@/hooks/useChatStream";

function message(overrides: Partial<DisplayMessage> = {}): DisplayMessage {
  return {
    id: "client-1",
    role: "assistant",
    content: "IS 15111 covers LED luminaires [1].",
    serverMessageId: "srv-msg-1",
    serverConversationId: "srv-conv-1",
    ...overrides,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("MessageActions", () => {
  it("submits a thumbs-up against the server-side ids, not the client id", async () => {
    const submit = vi.spyOn(api, "submitFeedback").mockResolvedValue({ status: "ok" });
    render(<MessageActions message={message()} />);

    await userEvent.setup().click(screen.getByRole("button", { name: "Helpful" }));

    await waitFor(() =>
      expect(submit).toHaveBeenCalledWith("srv-conv-1", "srv-msg-1", 1),
    );
  });

  it("clicking the same rating twice clears it back to 0", async () => {
    const submit = vi.spyOn(api, "submitFeedback").mockResolvedValue({ status: "ok" });
    render(<MessageActions message={message()} />);

    const user = userEvent.setup();
    const thumbsDown = screen.getByRole("button", { name: "Not helpful" });
    await user.click(thumbsDown);
    await waitFor(() => expect(submit).toHaveBeenCalledWith("srv-conv-1", "srv-msg-1", -1));

    await user.click(thumbsDown);
    await waitFor(() => expect(submit).toHaveBeenLastCalledWith("srv-conv-1", "srv-msg-1", 0));
  });

  it("hides rating controls until the server ids have arrived", () => {
    render(
      <MessageActions
        message={message({ serverMessageId: undefined, serverConversationId: undefined })}
      />,
    );

    expect(screen.queryByRole("button", { name: "Helpful" })).not.toBeInTheDocument();
    // Copy stays available — it only needs the text, not a persisted row.
    expect(screen.getByRole("button", { name: /copy answer/i })).toBeInTheDocument();
  });

  it("reverts the rating when the request fails", async () => {
    vi.spyOn(api, "submitFeedback").mockRejectedValue(new Error("network"));
    render(<MessageActions message={message()} />);

    const thumbsUp = screen.getByRole("button", { name: "Helpful" });
    await userEvent.setup().click(thumbsUp);

    await waitFor(() => expect(screen.getByText(/rating failed/i)).toBeInTheDocument());
    expect(thumbsUp).toHaveAttribute("aria-pressed", "false");
  });

  it("shows the answer latency when the backend reported one", () => {
    render(<MessageActions message={message({ latencyMs: 4200 })} />);
    expect(screen.getByText("4.2s")).toBeInTheDocument();
  });
});
