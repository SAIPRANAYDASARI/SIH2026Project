/**
 * Splits message text on the `[N]` citation markers the backend's prompt
 * asks the model to produce and the citation validator parses back out
 * (see `app.answer.citations` / `app.answer.prompts` — both sides must
 * agree on this exact `[N]` convention). Used by `ChatMessage` to render
 * each marker as a clickable element pointing at `CitationPanel`.
 */

const CITATION_MARKER_PATTERN = /\[(\d+)\]/g;

export type MessageSegment = { type: "text"; text: string } | { type: "citation"; marker: number };

export function splitOnCitationMarkers(content: string): MessageSegment[] {
  const segments: MessageSegment[] = [];
  let lastIndex = 0;

  for (const match of content.matchAll(CITATION_MARKER_PATTERN)) {
    const index = match.index ?? 0;
    if (index > lastIndex) {
      segments.push({ type: "text", text: content.slice(lastIndex, index) });
    }
    segments.push({ type: "citation", marker: Number(match[1]) });
    lastIndex = index + match[0].length;
  }

  if (lastIndex < content.length) {
    segments.push({ type: "text", text: content.slice(lastIndex) });
  }

  return segments;
}
