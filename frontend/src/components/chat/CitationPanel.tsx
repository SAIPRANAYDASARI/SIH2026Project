import { ExternalLink } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { DisplayMessage } from "@/hooks/useChatStream";

interface CitationPanelProps {
  message: DisplayMessage | null;
  activeMarker: number | null;
}

/**
 * The citation panel named in the brief's Step 7 scope: shows exactly what
 * the currently selected answer actually cited, resolved to real source
 * metadata by the backend's citation validator (`app.answer.citations`) —
 * never just the model's raw bracket text. Also surfaces any marker the
 * model invented (a real failure mode on smaller/free-tier hosted models,
 * see docs/DECISIONS.md Step 5) rather than hiding it.
 */
export function CitationPanel({ message, activeMarker }: CitationPanelProps): JSX.Element {
  return (
    <Card className="flex h-full flex-col">
      <CardHeader>
        <CardTitle>Sources</CardTitle>
      </CardHeader>
      {/* min-h-0: same reason as the chat list — without it this grows to fit
          all citations instead of scrolling inside the panel. */}
      <CardContent className="aurora-scroll min-h-0 flex-1 overflow-y-auto">
        {!message && (
          <p className="text-sm text-muted-foreground">
            Ask a question — citations for the answer will appear here.
          </p>
        )}

        {message && (message.citations?.length ?? 0) === 0 && !message.forcedRefusal && (
          <p className="text-sm text-muted-foreground">This answer had no citable sources.</p>
        )}

        {message?.forcedRefusal && (
          <p className="text-sm text-muted-foreground">
            Nothing was retrieved from indexed sources for this question.
          </p>
        )}

        {message && (message.citations?.length ?? 0) > 0 && (
          <ul className="flex flex-col gap-3">
            {message.citations!.map((citation, index) => (
              <li
                key={citation.marker}
                id={`citation-${message.id}-${citation.marker}`}
                style={{ animationDelay: `${index * 60}ms` }}
                className={cn(
                  "animate-fade-slide-up rounded-xl border border-border/60 bg-surface/50 p-3 text-sm " +
                    "backdrop-blur-md transition-shadow hover:shadow-glow",
                  activeMarker === citation.marker && "ring-2 ring-primary shadow-glow",
                )}
              >
                <div className="mb-1 flex items-center gap-2">
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-primary to-glow text-xs font-semibold text-primary-foreground">
                    {citation.marker}
                  </span>
                  <span className="font-medium">{citation.is_number ?? "No IS number"}</span>
                </div>
                {citation.clause_number && (
                  <p className="text-xs text-muted-foreground">Clause {citation.clause_number}</p>
                )}
                <p className="mt-1">{citation.document_title ?? "Untitled source"}</p>
                {citation.document_source_url && (
                  <a
                    href={citation.document_source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-1 inline-flex items-center gap-1 text-xs text-primary hover:underline"
                  >
                    View source <ExternalLink className="h-3 w-3" aria-hidden="true" />
                  </a>
                )}
              </li>
            ))}
          </ul>
        )}

        {message && (message.invalidCitationMarkers?.length ?? 0) > 0 && (
          <p className="mt-3 text-xs text-warning">
            The model also referenced source
            {message.invalidCitationMarkers!.length > 1 ? "s" : ""} [
            {message.invalidCitationMarkers!.join(", ")}] which don&apos;t match any retrieved
            context — treat those claims as unverified.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
