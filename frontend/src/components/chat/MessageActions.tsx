import { Check, Copy, ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";

import { submitFeedback } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { DisplayMessage } from "@/hooks/useChatStream";

interface MessageActionsProps {
  message: DisplayMessage;
}

type Rating = -1 | 0 | 1;

/**
 * Per-answer actions: copy the text, and rate it up/down.
 *
 * The rating goes to `PATCH /conversations/{cid}/messages/{mid}/feedback`,
 * which is what populates the officer dashboard's
 * `feedback_thumbs_up`/`feedback_thumbs_down`/`feedback_response_rate`
 * metrics — without a control here those charts can never be non-zero.
 * Clicking an already-selected rating clears it (sends 0), matching the
 * endpoint's `-1 | 0 | 1` contract.
 */
export function MessageActions({ message }: MessageActionsProps): JSX.Element | null {
  const [rating, setRating] = useState<Rating>(0);
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);

  // Feedback needs the server-side ids, which only exist once the `final`
  // event has landed; a still-streaming bubble has nothing to address.
  const canRate = Boolean(message.serverMessageId && message.serverConversationId);

  const handleCopy = async (): Promise<void> => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard can be unavailable (insecure origin, denied permission) —
      // silently skip rather than showing an error for a convenience action.
    }
  };

  const handleRate = async (next: Rating): Promise<void> => {
    if (!canRate) return;
    const applied: Rating = rating === next ? 0 : next;
    setRating(applied);
    setFailed(false);
    try {
      await submitFeedback(message.serverConversationId!, message.serverMessageId!, applied);
    } catch {
      setRating(rating);
      setFailed(true);
    }
  };

  return (
    <div className="mt-2 flex items-center gap-1">
      <button
        type="button"
        onClick={() => void handleCopy()}
        aria-label={copied ? "Answer copied" : "Copy answer"}
        title="Copy answer"
        className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary"
      >
        {copied ? (
          <Check className="h-3.5 w-3.5 text-success" aria-hidden="true" />
        ) : (
          <Copy className="h-3.5 w-3.5" aria-hidden="true" />
        )}
      </button>

      {canRate && (
        <>
          <button
            type="button"
            onClick={() => void handleRate(1)}
            aria-label="Helpful"
            aria-pressed={rating === 1}
            title="Helpful"
            className={cn(
              "rounded-md p-1.5 transition-colors hover:bg-primary/10",
              rating === 1 ? "text-success" : "text-muted-foreground hover:text-primary",
            )}
          >
            <ThumbsUp className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
          <button
            type="button"
            onClick={() => void handleRate(-1)}
            aria-label="Not helpful"
            aria-pressed={rating === -1}
            title="Not helpful"
            className={cn(
              "rounded-md p-1.5 transition-colors hover:bg-primary/10",
              rating === -1 ? "text-destructive" : "text-muted-foreground hover:text-primary",
            )}
          >
            <ThumbsDown className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </>
      )}

      {typeof message.latencyMs === "number" && (
        <span className="ml-1 text-[0.65rem] tabular-nums text-muted-foreground/70">
          {(message.latencyMs / 1000).toFixed(1)}s
        </span>
      )}

      {failed && <span className="ml-1 text-[0.65rem] text-destructive">rating failed</span>}
    </div>
  );
}
