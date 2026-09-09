import { AlertTriangle, Sparkles, User } from "lucide-react";

import { MessageActions } from "@/components/chat/MessageActions";
import { Badge } from "@/components/ui/badge";
import { splitOnCitationMarkers } from "@/lib/citations";
import { cn } from "@/lib/utils";
import type { DisplayMessage } from "@/hooks/useChatStream";

interface ChatMessageProps {
  message: DisplayMessage;
  onCitationClick: (messageId: string, marker: number) => void;
  isActive: boolean;
}

/** Three dots that rise in sequence — shown instead of the answer text
 * while the model is still working and hasn't emitted a token yet, which
 * on a reasoning model can be tens of seconds of otherwise-blank bubble. */
function TypingDots(): JSX.Element {
  return (
    <span className="flex items-center gap-1 py-0.5" aria-label="Generating answer">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-1.5 w-1.5 animate-dot-bounce rounded-full bg-primary"
          style={{ animationDelay: `${i * 0.16}s` }}
        />
      ))}
    </span>
  );
}

/** One chat bubble. For an assistant message, `[N]` citation markers in the
 * text become clickable — clicking one opens `CitationPanel` scoped to
 * this message and highlighted on that marker. */
export function ChatMessage({ message, onCitationClick, isActive }: ChatMessageProps): JSX.Element {
  const isUser = message.role === "user";
  const segments = splitOnCitationMarkers(message.content);
  const hasInvalidCitations = (message.invalidCitationMarkers?.length ?? 0) > 0;
  const hasGuardrailNotice = (message.guardrailViolations?.length ?? 0) > 0;
  const awaitingFirstToken = message.isStreaming && message.content.length === 0;

  return (
    <div
      className={cn(
        "flex w-full animate-fade-slide-up gap-2.5",
        isUser ? "flex-row-reverse" : "flex-row",
      )}
    >
      <div
        aria-hidden="true"
        className={cn(
          "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border",
          isUser
            ? "border-primary/40 bg-primary/15 text-primary"
            : "border-border/60 bg-surface/70 text-primary",
        )}
      >
        {isUser ? <User className="h-3.5 w-3.5" /> : <Sparkles className="h-3.5 w-3.5" />}
      </div>

      <div className={cn("flex min-w-0 max-w-[42rem] flex-col", isUser && "items-end")}>
        <div
          className={cn(
            "rounded-2xl px-4 py-3 text-sm leading-relaxed backdrop-blur-xl transition-shadow",
            isUser
              ? "bg-gradient-to-br from-primary to-glow text-primary-foreground shadow-glow"
              : "border border-border/60 bg-surface/70 shadow-glass",
            !isUser && isActive && "ring-1 ring-primary/60 shadow-glow",
          )}
        >
          {message.forcedRefusal && (
            <div className="mb-2 flex items-center gap-1.5 text-xs text-muted-foreground">
              <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
              <span>Not answered from an LLM — nothing was found in indexed sources.</span>
            </div>
          )}

          {awaitingFirstToken ? (
            <TypingDots />
          ) : (
            <p className="whitespace-pre-wrap">
              {segments.map((segment, i) =>
                segment.type === "text" ? (
                  <span key={i}>{segment.text}</span>
                ) : (
                  <button
                    key={i}
                    type="button"
                    onClick={() => onCitationClick(message.id, segment.marker)}
                    className="mx-0.5 rounded-full bg-primary/15 px-1.5 font-medium text-primary transition-colors hover:bg-primary/30"
                    aria-label={`Show source ${segment.marker}`}
                  >
                    [{segment.marker}]
                  </button>
                ),
              )}
              {message.isStreaming && (
                <span
                  className="ml-0.5 inline-block h-3.5 w-1.5 animate-glow-pulse rounded-sm bg-current align-middle"
                  aria-hidden="true"
                />
              )}
            </p>
          )}

          {(hasInvalidCitations || hasGuardrailNotice) && !message.isStreaming && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {hasInvalidCitations && (
                <Badge
                  variant="warning"
                  title="The model referenced a source number with no matching context."
                >
                  unverified citation
                </Badge>
              )}
              {hasGuardrailNotice && (
                <Badge
                  variant="secondary"
                  title="A long verbatim quote from a standard was redacted — see the cited clause for the original."
                >
                  text redacted
                </Badge>
              )}
            </div>
          )}
        </div>

        {!isUser && !message.isStreaming && message.content.length > 0 && (
          <MessageActions message={message} />
        )}
      </div>
    </div>
  );
}
