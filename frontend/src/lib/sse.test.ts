import { describe, expect, it } from "vitest";

import { parseSSEStream } from "@/lib/sse";

function streamFrom(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

describe("parseSSEStream", () => {
  it("parses complete event/data blocks separated by blank lines", async () => {
    const stream = streamFrom(['event: token\ndata: {"text":"hi"}\n\n']);
    const events = [];
    for await (const event of parseSSEStream(stream)) events.push(event);

    expect(events).toEqual([{ event: "token", data: '{"text":"hi"}' }]);
  });

  it("handles multiple events arriving across separate chunks", async () => {
    const stream = streamFrom([
      "event: conversation\ndata:",
      ' {"conversation_id":"abc"}\n\n',
      'event: token\ndata: {"text":"a"}\n\nevent: token\ndata: {"text":"b"}\n\n',
    ]);
    const events = [];
    for await (const event of parseSSEStream(stream)) events.push(event);

    expect(events).toEqual([
      { event: "conversation", data: '{"conversation_id":"abc"}' },
      { event: "token", data: '{"text":"a"}' },
      { event: "token", data: '{"text":"b"}' },
    ]);
  });

  it("ignores an incomplete trailing block with no blank-line terminator", async () => {
    const stream = streamFrom([
      'event: token\ndata: {"text":"a"}\n\nevent: token\ndata: incomplete',
    ]);
    const events = [];
    for await (const event of parseSSEStream(stream)) events.push(event);

    expect(events).toEqual([{ event: "token", data: '{"text":"a"}' }]);
  });

  it("yields nothing for an empty stream", async () => {
    const stream = streamFrom([]);
    const events = [];
    for await (const event of parseSSEStream(stream)) events.push(event);
    expect(events).toEqual([]);
  });
});
