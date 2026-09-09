/**
 * Parses a Server-Sent Events stream out of a `fetch()` response body.
 *
 * The browser's native `EventSource` can't be used for POST /api/v1/chat:
 * it only supports GET requests with no custom body, and this endpoint
 * needs a JSON body (the chat message) plus the session cookie sent
 * automatically by `fetch`'s `credentials: "same-origin"` default. So this
 * reads the raw byte stream and re-implements the (simple) SSE framing:
 * blocks separated by a blank line, each with an `event:` and `data:`
 * line — exactly what `app.api.v1.chat._sse_event` on the backend writes.
 */

export interface SSEEvent {
  event: string;
  data: string;
}

export async function* parseSSEStream(body: ReadableStream<Uint8Array>): AsyncGenerator<SSEEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const parsed = parseSSEBlock(block);
        if (parsed) yield parsed;
        boundary = buffer.indexOf("\n\n");
      }
    }
  } finally {
    reader.releaseLock();
  }
}

function parseSSEBlock(block: string): SSEEvent | null {
  let event: string | null = null;
  let data: string | null = null;

  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) {
      event = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      data = line.slice("data:".length).trim();
    }
  }

  if (event === null || data === null) return null;
  return { event, data };
}
