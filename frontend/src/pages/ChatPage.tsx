import { useQuery } from "@tanstack/react-query";
import { Download, PanelLeft, RotateCcw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { AuroraBackground } from "@/components/background/AuroraBackground";
import { AudienceToggle } from "@/components/chat/AudienceToggle";
import { ChatInput } from "@/components/chat/ChatInput";
import { CitationPanel } from "@/components/chat/CitationPanel";
import { ChatWindow } from "@/components/chat/ChatWindow";
import { HistorySidebar } from "@/components/chat/HistorySidebar";
import { LanguageToggle } from "@/components/chat/LanguageToggle";
import { Badge } from "@/components/ui/badge";
import { useChatStream } from "@/hooks/useChatStream";
import { getHealth } from "@/lib/api";
import { conversationToMarkdown, downloadTextFile } from "@/lib/export";
import { cn } from "@/lib/utils";
import type { Audience, Language } from "@/types/api";

/** Maps backend health to a small unobtrusive status dot rather than a
 * whole page (that was Step 1's placeholder shell) — useful for local
 * development/demo triage without competing with the chat UI for
 * attention. */
function HealthBadge(): JSX.Element | null {
  const { data, isError } = useQuery({ queryKey: ["health"], queryFn: getHealth, retry: false });

  if (isError) return <Badge variant="destructive">backend unreachable</Badge>;
  if (!data) return null;
  const degraded = data.database !== "ok" || data.redis !== "ok";
  return (
    <Badge variant={degraded ? "warning" : "secondary"} title={`llm: ${data.llm_backend}`}>
      <span
        className={cn(
          "mr-1.5 h-1.5 w-1.5 rounded-full",
          degraded ? "bg-warning" : "animate-glow-pulse bg-success",
        )}
        aria-hidden="true"
      />
      {degraded ? "degraded" : "online"}
    </Badge>
  );
}

export function ChatPage(): JSX.Element {
  const [audience, setAudience] = useState<Audience>("consumer");
  const [language, setLanguage] = useState<Language>("en");
  const [activeMessageId, setActiveMessageId] = useState<string | null>(null);
  const [activeMarker, setActiveMarker] = useState<number | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);
  const {
    messages,
    conversationId,
    isStreaming,
    error,
    sendMessage,
    stop,
    loadConversation,
    lastUserMessage,
  } = useChatStream();

  const activeMessage = messages.find((m) => m.id === activeMessageId) ?? null;

  // Auto-follows the newest assistant message as the one the citation
  // panel shows, from the moment its (empty, streaming) bubble appears —
  // a manual citation click below overrides this until the next send,
  // since that push always adds a new latest message and re-triggers this.
  const previousMessageCount = useRef(0);
  useEffect(() => {
    if (messages.length <= previousMessageCount.current) return;
    previousMessageCount.current = messages.length;
    const latestAssistant = [...messages].reverse().find((m) => m.role === "assistant");
    if (latestAssistant) {
      setActiveMessageId(latestAssistant.id);
      setActiveMarker(null);
    }
  }, [messages]);

  // Refresh the history list once a turn finishes, so a brand-new thread
  // (and the title derived from its first question) shows up.
  useEffect(() => {
    if (!isStreaming && conversationId) setHistoryRefreshKey((k) => k + 1);
  }, [isStreaming, conversationId]);

  const handleCitationClick = (messageId: string, marker: number): void => {
    setActiveMessageId(messageId);
    setActiveMarker(marker);
    document
      .getElementById(`citation-${messageId}-${marker}`)
      ?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };

  const handleSend = (text: string): void => {
    void sendMessage(text, audience, language);
  };

  const handleSelectConversation = (id: string | null): void => {
    void loadConversation(id);
    previousMessageCount.current = 0;
    setActiveMessageId(null);
    setActiveMarker(null);
    setHistoryOpen(false);
  };

  const handleExport = (): void => {
    downloadTextFile(
      `manak-sahayak-${new Date().toISOString().slice(0, 10)}.md`,
      conversationToMarkdown(messages),
    );
  };

  const canRetry = Boolean(error && lastUserMessage && !isStreaming);

  return (
    <div className="relative flex h-screen flex-col overflow-hidden">
      <AuroraBackground />

      <header className="edge-lit relative z-10 flex flex-wrap items-center justify-between gap-x-4 gap-y-3 border-b border-border/40 bg-surface/40 px-4 py-3 backdrop-blur-xl">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setHistoryOpen((open) => !open)}
            aria-label="Toggle conversation history"
            aria-expanded={historyOpen}
            className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary lg:hidden"
          >
            <PanelLeft className="h-4 w-4" aria-hidden="true" />
          </button>

          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-primary/30 bg-gradient-to-br from-primary/25 to-glow/10 text-primary shadow-glow">
            <span className="text-base font-semibold">म</span>
          </div>
          <div>
            <h1 className="bg-gradient-to-r from-primary to-glow bg-clip-text text-lg font-semibold leading-tight tracking-tight text-transparent">
              Manak Sahayak
            </h1>
            <p className="text-xs text-muted-foreground">
              Indian Standards &amp; BIS certification assistant
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          {messages.length > 0 && (
            <button
              type="button"
              onClick={handleExport}
              title="Export this conversation as Markdown"
              className="flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary"
            >
              <Download className="h-3.5 w-3.5" aria-hidden="true" />
              Export
            </button>
          )}
          <nav className="flex items-center gap-1 text-xs">
            <Link
              to="/tools"
              className="rounded-full px-2.5 py-1 text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary"
            >
              Tools
            </Link>
            <Link
              to="/dashboard"
              className="rounded-full px-2.5 py-1 text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary"
            >
              Dashboard
            </Link>
          </nav>
          <HealthBadge />
          <LanguageToggle value={language} onChange={setLanguage} disabled={isStreaming} />
          <AudienceToggle value={audience} onChange={setAudience} disabled={isStreaming} />
        </div>
      </header>

      {error && (
        <div
          role="alert"
          className="relative z-10 flex animate-fade-slide-up flex-wrap items-center justify-between gap-2 border-b border-destructive/30 bg-destructive/10 px-4 py-2 text-sm text-destructive backdrop-blur-md"
        >
          <span>{error}</span>
          {canRetry && (
            <button
              type="button"
              onClick={() => handleSend(lastUserMessage!)}
              className="flex items-center gap-1.5 rounded-full border border-destructive/40 px-2.5 py-1 text-xs font-medium transition-colors hover:bg-destructive/20"
            >
              <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
              Retry
            </button>
          )}
        </div>
      )}

      {/* `min-h-0` on this grid and on each of its items is load-bearing, not
          cosmetic: grid/flex items default to `min-height: auto`, which
          refuses to shrink below content height. Without it a long answer
          makes the column grow past the viewport instead of scrolling — the
          inner `overflow-y-auto` never engages, and the composer gets pushed
          out of view with no scrollbar anywhere to get back to it. */}
      <main className="relative z-10 grid min-h-0 flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[15rem_1fr_20rem]">
        <aside
          className={cn(
            "min-h-0 overflow-hidden border-border/30 p-3 lg:block lg:border-r",
            historyOpen ? "block" : "hidden",
          )}
        >
          <HistorySidebar
            activeConversationId={conversationId}
            onSelect={handleSelectConversation}
            refreshKey={historyRefreshKey}
          />
        </aside>

        <div className="flex min-h-0 min-w-0 flex-col border-border/30 md:border-r">
          <ChatWindow
            messages={messages}
            activeMessageId={activeMessageId}
            onCitationClick={handleCitationClick}
            onSuggestionClick={handleSend}
          />
          <ChatInput onSend={handleSend} onStop={stop} isStreaming={isStreaming} />
        </div>

        <aside className="hidden min-h-0 overflow-hidden p-3 md:block">
          <CitationPanel message={activeMessage} activeMarker={activeMarker} />
        </aside>
      </main>
    </div>
  );
}
