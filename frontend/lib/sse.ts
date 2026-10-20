/**
 * Incremental Server-Sent Events parsing.
 *
 * `fetch` hands over text chunks that can split a frame anywhere —
 * between `id:` and `data:`, or in the middle of a JSON payload. This
 * module is therefore a pure `(chunk) => {frames, rest}` fold: the caller
 * keeps `rest`, prepends it to the next chunk, and gets every complete
 * frame exactly once. Nothing here touches the network, so the awkward
 * cases are unit-testable without a server.
 *
 * Only what the backend emits is supported: `id`, `event`, `data`, and
 * comment lines (which the server may send as a keep-alive).
 */

export type SseFrame = {
  /** `id:` — what `Last-Event-ID` sends back. Null when absent. */
  id: string | null;
  event: string;
  /** `data:` lines joined by newlines, exactly as sent. */
  data: string;
};

export type ParsedChunk = {
  frames: SseFrame[];
  /** The incomplete tail; prepend it to the next chunk. */
  rest: string;
};

export function parseFrames(chunk: string): ParsedChunk {
  // Normalise once so the terminator is always a bare "\n\n".
  const normalised = chunk.replace(/\r\n/g, "\n");
  const blocks = normalised.split("\n\n");
  const rest = blocks.pop() ?? "";
  const frames: SseFrame[] = [];

  for (const block of blocks) {
    const frame = parseBlock(block);
    if (frame) frames.push(frame);
  }

  return { frames, rest };
}

/** `null` when the block carries no `data:` field — an empty frame is not
 * an event, and treating it as one would show the UI an empty update. */
function parseBlock(block: string): SseFrame | null {
  let id: string | null = null;
  let event = "message";
  const data: string[] = [];

  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) continue; // comment / keep-alive
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    // A single leading space after the colon is part of the framing.
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);

    if (field === "id") id = value;
    else if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }

  if (data.length === 0) return null;
  return { id, event, data: data.join("\n") };
}