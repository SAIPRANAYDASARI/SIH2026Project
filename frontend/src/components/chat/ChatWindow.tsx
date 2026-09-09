import { useEffect, useRef } from "react";

import { ChatMessage } from "@/components/chat/ChatMessage";
import type { DisplayMessage } from "@/hooks/useChatStream";

interface ChatWindowProps {
  messages: DisplayMessage[];
  activeMessageId: string | null;
  onCitationClick: (messageId: string, marker: number) => void;
  onSuggestionClick: (text: string) => void;
}

/** Starter questions for the empty state. Chosen to match what the
 * crawlers actually index (hallmarking/HUID, Eco Mark, CRS, complaints),
 * so a first-time click lands on a genuinely cited answer rather than the
 * "nothing found in indexed sources" refusal. */
const SUGGESTIONS = [
  "What is hallmarking and what is HUID?",
  "What is the Eco Mark scheme?",
  "Which products need CRS registration?",
  "How do I report a fake ISI mark?",
];

export function ChatWindow({
  messages,
  activeMessageId,
  onCitationClick,
  onSuggestionClick,
}: ChatWindowProps): JSX.Element {
  const scrollRef = useRef<HTMLDivElement>(null);
  // Whether the view should stay pinned to the newest message. Starts true
  // and flips off as soon as the reader scrolls away from the bottom.
  const stickToBottom = useRef(true);

  const handleScroll = (): void => {
    const el = scrollRef.current;
    if (!el) return;
    // A few px of slack: smooth scrolling and sub-pixel layout mean the
    // "at the bottom" position is rarely an exact match.
    stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
  };

  useEffect(() => {
    const el = scrollRef.current;
    // Only follow new content when the reader hasn't scrolled up. Otherwise
    // every streamed token would yank them back down mid-sentence, which is
    // exactly when someone is most likely to be re-reading earlier text.
    if (!el || !stickToBottom.current) return;
    el.scrollTop = el.scrollHeight;
  }, [messages]);

  // `min-h-0` lets this shrink below its content height so `overflow-y-auto`
  // actually scrolls; without it the list grows and the composer below is
  // pushed off-screen. See the note on <main> in ChatPage.
  return (
    <div
      ref={scrollRef}
      onScroll={handleScroll}
      aria-live="polite"
      className="aurora-scroll flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4"
    >
      {messages.length === 0 && (
        <div className="m-auto flex w-full max-w-lg animate-fade-slide-up flex-col items-center gap-5 text-center">
          <div className="flex h-14 w-14 animate-float items-center justify-center rounded-2xl border border-primary/30 bg-gradient-to-br from-primary/20 to-glow/10 shadow-glow">
            <span className="text-2xl">✦</span>
          </div>

          <div className="flex flex-col gap-1.5">
            <h2 className="bg-gradient-to-r from-primary to-glow bg-clip-text text-xl font-semibold text-transparent">
              Ask about Indian Standards
            </h2>
            <p className="text-sm text-muted-foreground">
              BIS certification schemes, what a mark means, or how to verify a licence. Every
              answer is grounded in indexed BIS sources and cites where it came from.
            </p>
          </div>

          <div className="flex flex-wrap justify-center gap-2">
            {SUGGESTIONS.map((suggestion, i) => (
              <button
                key={suggestion}
                type="button"
                onClick={() => onSuggestionClick(suggestion)}
                style={{ animationDelay: `${120 + i * 70}ms` }}
                className="animate-fade-slide-up rounded-full border border-border/60 bg-surface/60 px-3 py-1.5 text-xs text-muted-foreground backdrop-blur-md transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/50 hover:text-foreground hover:shadow-glow"
              >
                {suggestion}
              </button>
            ))}
          </div>
        </div>
      )}

      {messages.map((message) => (
        <ChatMessage
          key={message.id}
          message={message}
          isActive={message.id === activeMessageId}
          onCitationClick={onCitationClick}
        />
      ))}
    </div>
  );
}
