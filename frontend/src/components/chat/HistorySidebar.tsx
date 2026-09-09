import { useQuery } from "@tanstack/react-query";
import { MessageSquare, Plus } from "lucide-react";

import { listConversations } from "@/lib/api";
import { cn } from "@/lib/utils";

interface HistorySidebarProps {
  activeConversationId: string | null;
  onSelect: (conversationId: string | null) => void;
  /** Bumped by the parent after each completed answer so the list picks up
   * a newly-created thread (and its derived title) without a manual
   * refresh. */
  refreshKey: number;
}

function formatWhen(iso: string): string {
  const date = new Date(iso);
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  return sameDay
    ? date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
    : date.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/**
 * Past conversations for this browser, from `GET /conversations`. Scoped
 * server-side to the caller's signed session cookie — there's no login, so
 * "history" means "this browser's threads", nobody else's.
 */
export function HistorySidebar({
  activeConversationId,
  onSelect,
  refreshKey,
}: HistorySidebarProps): JSX.Element {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["conversations", refreshKey],
    queryFn: listConversations,
    retry: false,
  });

  return (
    <div className="flex h-full flex-col gap-2 overflow-hidden">
      <button
        type="button"
        onClick={() => onSelect(null)}
        className="flex items-center gap-2 rounded-lg border border-border/60 bg-surface/60 px-3 py-2 text-sm font-medium backdrop-blur-md transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-glow"
      >
        <Plus className="h-4 w-4 text-primary" aria-hidden="true" />
        New conversation
      </button>

      <p className="px-1 pt-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        History
      </p>

      {/* min-h-0: same reason as the chat list — lets a long history scroll
          inside the sidebar instead of stretching it past the viewport. */}
      <div className="aurora-scroll min-h-0 flex-1 overflow-y-auto">
        {isLoading && <p className="px-1 text-xs text-muted-foreground">Loading…</p>}
        {isError && <p className="px-1 text-xs text-destructive">Couldn&apos;t load history.</p>}
        {data?.length === 0 && (
          <p className="px-1 text-xs text-muted-foreground">
            Your past conversations will appear here.
          </p>
        )}

        <ul className="flex flex-col gap-1">
          {data?.map((conversation) => (
            <li key={conversation.id}>
              <button
                type="button"
                onClick={() => onSelect(conversation.id)}
                className={cn(
                  "flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left text-xs transition-colors",
                  conversation.id === activeConversationId
                    ? "bg-primary/15 text-foreground ring-1 ring-primary/40"
                    : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                )}
              >
                <MessageSquare className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                <span className="min-w-0 flex-1">
                  <span className="line-clamp-2 block">
                    {conversation.title ?? "Untitled conversation"}
                  </span>
                  <span className="mt-0.5 block text-[0.65rem] text-muted-foreground/70">
                    {formatWhen(conversation.created_at)} · {conversation.audience}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
