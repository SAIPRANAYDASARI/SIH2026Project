import { describe, expect, it } from "vitest";

import { splitOnCitationMarkers } from "@/lib/citations";

describe("splitOnCitationMarkers", () => {
  it("splits text around a single marker", () => {
    expect(splitOnCitationMarkers("Applies here [1] as required.")).toEqual([
      { type: "text", text: "Applies here " },
      { type: "citation", marker: 1 },
      { type: "text", text: " as required." },
    ]);
  });

  it("handles adjacent markers with no text between them", () => {
    expect(splitOnCitationMarkers("Two sources [1][2].")).toEqual([
      { type: "text", text: "Two sources " },
      { type: "citation", marker: 1 },
      { type: "citation", marker: 2 },
      { type: "text", text: "." },
    ]);
  });

  it("returns a single text segment when there are no markers", () => {
    expect(splitOnCitationMarkers("No citations here.")).toEqual([
      { type: "text", text: "No citations here." },
    ]);
  });

  it("handles a marker at the very start or end", () => {
    expect(splitOnCitationMarkers("[1] leads.")).toEqual([
      { type: "citation", marker: 1 },
      { type: "text", text: " leads." },
    ]);
    expect(splitOnCitationMarkers("trails [2]")).toEqual([
      { type: "text", text: "trails " },
      { type: "citation", marker: 2 },
    ]);
  });

  it("handles multi-digit marker numbers", () => {
    expect(splitOnCitationMarkers("[12]")).toEqual([{ type: "citation", marker: 12 }]);
  });
});
