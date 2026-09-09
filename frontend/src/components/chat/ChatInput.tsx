import { Send, Square } from "lucide-react";
import { useState } from "react";
import type { KeyboardEvent } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

interface ChatInputProps {
  onSend: (text: string) => void;
  onStop: () => void;
  isStreaming: boolean;
}

/** Matches `ChatRequest.message`'s `max_length=4000` on the backend, so an
 * over-long message is caught here rather than as a 422. */
const MAX_LENGTH = 4000;

export function ChatInput({ onSend, onStop, isStreaming }: ChatInputProps): JSX.Element {
  const [value, setValue] = useState("");

  const submit = (): void => {
    if (!value.trim() || isStreaming) return;
    onSend(value);
    setValue("");
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>): void => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  };

  const nearLimit = value.length > MAX_LENGTH * 0.9;

  return (
    <div className="edge-lit border-t border-border/40 bg-surface/40 p-3 backdrop-blur-xl">
      <div className="flex items-end gap-2">
        <Textarea
          value={value}
          onChange={(e) => setValue(e.target.value.slice(0, MAX_LENGTH))}
          onKeyDown={handleKeyDown}
          placeholder="Ask about a standard, scheme, or how to verify a mark…"
          rows={2}
          aria-label="Message"
          className="min-h-[2.5rem]"
        />
        {isStreaming ? (
          <Button type="button" variant="outline" onClick={onStop} aria-label="Stop generating">
            <Square className="h-4 w-4" aria-hidden="true" />
          </Button>
        ) : (
          <Button type="button" onClick={submit} disabled={!value.trim()} aria-label="Send message">
            <Send className="h-4 w-4" aria-hidden="true" />
          </Button>
        )}
      </div>

      <div className="mt-1.5 flex items-center justify-between px-1 text-[0.65rem] text-muted-foreground/70">
        <span>
          <kbd className="rounded border border-border/60 px-1 font-sans">Enter</kbd> to send ·{" "}
          <kbd className="rounded border border-border/60 px-1 font-sans">Shift+Enter</kbd> for a
          new line
        </span>
        {nearLimit && (
          <span className="tabular-nums">
            {value.length} / {MAX_LENGTH}
          </span>
        )}
      </div>
    </div>
  );
}
