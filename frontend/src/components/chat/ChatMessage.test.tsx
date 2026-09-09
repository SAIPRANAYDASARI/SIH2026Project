import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ChatMessage } from "@/components/chat/ChatMessage";
import type { DisplayMessage } from "@/hooks/useChatStream";

function message(overrides: Partial<DisplayMessage> = {}): DisplayMessage {
  return { id: "m1", role: "assistant", content: "Applies here [1].", ...overrides };
}

describe("ChatMessage", () => {
  it("renders a citation marker as a clickable button and calls back with its number", async () => {
    const onCitationClick = vi.fn();
    render(<ChatMessage message={message()} isActive={false} onCitationClick={onCitationClick} />);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /show source 1/i }));

    expect(onCitationClick).toHaveBeenCalledWith("m1", 1);
  });

  it("shows the forced-refusal notice instead of treating it as a normal answer", () => {
    render(
      <ChatMessage
        message={message({ content: "Nothing found.", forcedRefusal: true })}
        isActive={false}
        onCitationClick={vi.fn()}
      />,
    );

    expect(screen.getByText(/nothing was found in indexed sources/i)).toBeInTheDocument();
  });

  it("shows an unverified-citation badge when the model cited a nonexistent source", () => {
    render(
      <ChatMessage
        message={message({ invalidCitationMarkers: [7] })}
        isActive={false}
        onCitationClick={vi.fn()}
      />,
    );

    expect(screen.getByText("unverified citation")).toBeInTheDocument();
  });

  it("shows a redaction badge when a guardrail fired", () => {
    render(
      <ChatMessage
        message={message({ guardrailViolations: ["redacted 1 verbatim run"] })}
        isActive={false}
        onCitationClick={vi.fn()}
      />,
    );

    expect(screen.getByText("text redacted")).toBeInTheDocument();
  });

  it("does not show quality badges while still streaming", () => {
    render(
      <ChatMessage
        message={message({ invalidCitationMarkers: [7], isStreaming: true })}
        isActive={false}
        onCitationClick={vi.fn()}
      />,
    );

    expect(screen.queryByText("unverified citation")).not.toBeInTheDocument();
  });
});
