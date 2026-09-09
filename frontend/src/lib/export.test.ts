import { describe, expect, it } from "vitest";

import { conversationToMarkdown } from "@/lib/export";
import type { DisplayMessage } from "@/hooks/useChatStream";

function citation(marker: number, isNumber: string | null) {
  return {
    marker,
    chunk_id: `c${marker}`,
    is_number: isNumber,
    clause_number: null,
    document_title: "Bureau of Indian Standards",
    document_source_url: "https://www.bis.gov.in/hallmarking/",
  };
}

describe("conversationToMarkdown", () => {
  it("renders questions and answers with each answer's own sources", () => {
    const messages: DisplayMessage[] = [
      { id: "1", role: "user", content: "What is hallmarking?" },
      {
        id: "2",
        role: "assistant",
        content: "Hallmarking certifies gold purity [1].",
        citations: [citation(1, "IS 1417")],
      },
    ];

    const md = conversationToMarkdown(messages);

    expect(md).toContain("## Question");
    expect(md).toContain("What is hallmarking?");
    expect(md).toContain("### Answer");
    expect(md).toContain("Hallmarking certifies gold purity [1].");
    expect(md).toContain("- [1] IS 1417 — https://www.bis.gov.in/hallmarking/");
  });

  it("falls back to the document title when a source has no IS number", () => {
    const messages: DisplayMessage[] = [
      { id: "1", role: "assistant", content: "See source [1].", citations: [citation(1, null)] },
    ];

    expect(conversationToMarkdown(messages)).toContain("- [1] Bureau of Indian Standards");
  });

  it("keeps each answer's sources in its own block so markers don't collide", () => {
    const messages: DisplayMessage[] = [
      { id: "1", role: "assistant", content: "First [1].", citations: [citation(1, "IS 111")] },
      { id: "2", role: "assistant", content: "Second [1].", citations: [citation(1, "IS 222")] },
    ];

    const md = conversationToMarkdown(messages);

    // Both answers legitimately use marker [1] for different sources.
    expect(md).toContain("- [1] IS 111");
    expect(md).toContain("- [1] IS 222");
    expect(md.match(/\*\*Sources\*\*/g)).toHaveLength(2);
  });

  it("notes a forced refusal so an exported transcript isn't misread as sourced", () => {
    const messages: DisplayMessage[] = [
      { id: "1", role: "assistant", content: "Nothing found.", forcedRefusal: true },
    ];

    expect(conversationToMarkdown(messages)).toContain("Not answered from an LLM");
  });
});
