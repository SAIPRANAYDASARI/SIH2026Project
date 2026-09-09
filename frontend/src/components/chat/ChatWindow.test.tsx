import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChatWindow } from "@/components/chat/ChatWindow";
import type { DisplayMessage } from "@/hooks/useChatStream";

function renderWindow(messages: DisplayMessage[]) {
  return render(
    <ChatWindow
      messages={messages}
      activeMessageId={null}
      onCitationClick={vi.fn()}
      onSuggestionClick={vi.fn()}
    />,
  );
}

/** The scroll container is the element carrying `aria-live` — the same node
 * the component attaches its ref and onScroll handler to. */
function scrollContainer(): HTMLElement {
  const el = document.querySelector('[aria-live="polite"]');
  if (!el) throw new Error("scroll container not found");
  return el as HTMLElement;
}

describe("ChatWindow", () => {
  it("keeps the transcript scrollable rather than growing past its parent", () => {
    // Regression guard: grid/flex children default to `min-height: auto`,
    // which makes a tall transcript stretch its column instead of scrolling
    // — that pushed the composer off-screen with no way to scroll back.
    renderWindow([
      { id: "1", role: "user", content: "What is hallmarking?" },
      { id: "2", role: "assistant", content: "A long answer.".repeat(200) },
    ]);

    const el = scrollContainer();
    expect(el.className).toContain("min-h-0");
    expect(el.className).toContain("overflow-y-auto");
  });

  it("follows new messages while the reader is at the bottom", () => {
    const first: DisplayMessage[] = [{ id: "1", role: "user", content: "Question" }];
    const { rerender } = renderWindow(first);

    const el = scrollContainer();
    // jsdom has no layout, so drive the geometry the component reads.
    Object.defineProperty(el, "clientHeight", { value: 100, configurable: true });
    Object.defineProperty(el, "scrollHeight", { value: 500, configurable: true });
    el.scrollTop = 0;

    rerender(
      <ChatWindow
        messages={[...first, { id: "2", role: "assistant", content: "Answer" }]}
        activeMessageId={null}
        onCitationClick={vi.fn()}
        onSuggestionClick={vi.fn()}
      />,
    );

    expect(el.scrollTop).toBe(500);
  });

  it("stops following once the reader scrolls up, so streaming can't yank them back", () => {
    const first: DisplayMessage[] = [{ id: "1", role: "user", content: "Question" }];
    const { rerender } = renderWindow(first);

    const el = scrollContainer();
    Object.defineProperty(el, "clientHeight", { value: 100, configurable: true });
    Object.defineProperty(el, "scrollHeight", { value: 500, configurable: true });

    // Reader scrolls well away from the bottom.
    el.scrollTop = 50;
    el.dispatchEvent(new Event("scroll", { bubbles: true }));

    rerender(
      <ChatWindow
        messages={[...first, { id: "2", role: "assistant", content: "Streaming…" }]}
        activeMessageId={null}
        onCitationClick={vi.fn()}
        onSuggestionClick={vi.fn()}
      />,
    );

    expect(el.scrollTop).toBe(50);
  });

  it("offers starter suggestions only while the transcript is empty", () => {
    const { rerender } = renderWindow([]);
    expect(screen.getByRole("button", { name: "What is the Eco Mark scheme?" })).toBeInTheDocument();

    rerender(
      <ChatWindow
        messages={[{ id: "1", role: "user", content: "Hi" }]}
        activeMessageId={null}
        onCitationClick={vi.fn()}
        onSuggestionClick={vi.fn()}
      />,
    );
    expect(
      screen.queryByRole("button", { name: "What is the Eco Mark scheme?" }),
    ).not.toBeInTheDocument();
  });
});
