import { describe, expect, it } from "vitest";

import { parseFrames } from "./sse";

/**
 * The SSE reader is the one piece of client-side logic that has to be
 * right about chunk boundaries: a network read can split a frame anywhere,
 * including between `id:` and `data:`. `parseFrames` returns whole frames
 * and holds back the incomplete tail, so the caller can feed it the next
 * chunk and get the frame exactly once.
 */
describe("parseFrames", () => {
  it("parses a single complete frame", () => {
    const { frames, rest } = parseFrames("id: 1\nevent: plan_ready\ndata: {}\n\n");

    expect(frames).toEqual([{ id: "1", event: "plan_ready", data: "{}" }]);
    expect(rest).toBe("");
  });

  it("parses several frames from one chunk", () => {
    const chunk =
      "id: 1\nevent: plan_ready\ndata: {\"a\":1}\n\n" +
      "id: 2\nevent: report_ready\ndata: {\"b\":2}\n\n";

    expect(parseFrames(chunk).frames.map((f) => f.event)).toEqual([
      "plan_ready",
      "report_ready",
    ]);
  });

  it("holds back a frame that has not arrived in full yet", () => {
    const { frames, rest } = parseFrames("id: 1\nevent: plan_ready\ndata: {\"a\":");

    expect(frames).toEqual([]);
    expect(rest).toBe("id: 1\nevent: plan_ready\ndata: {\"a\":");
  });

  it("completes a held-back frame on the next chunk", () => {
    const first = parseFrames("id: 1\nevent: plan_ready\ndata: {\"a\":");
    const second = parseFrames(first.rest + "1}\n\n");

    expect(second.frames).toEqual([
      { id: "1", event: "plan_ready", data: '{"a":1}' },
    ]);
  });

  it("joins multi-line data with newlines", () => {
    const { frames } = parseFrames("data: line one\ndata: line two\n\n");

    expect(frames[0].data).toBe("line one\nline two");
  });

  it("ignores comment lines", () => {
    const { frames } = parseFrames(": keep-alive\n\nid: 3\nevent: ping\ndata: {}\n\n");

    expect(frames).toEqual([{ id: "3", event: "ping", data: "{}" }]);
  });

  it("defaults event to message when the field is absent", () => {
    const { frames } = parseFrames("data: {}\n\n");

    expect(frames[0].event).toBe("message");
  });

  it("reports a frame with no id rather than inventing one", () => {
    const { frames } = parseFrames("event: plan_ready\ndata: {}\n\n");

    expect(frames[0].id).toBeNull();
  });

  it("discards a frame with no data field", () => {
    const { frames, rest } = parseFrames("id: 1\nevent: plan_ready\n\n");

    expect(frames).toEqual([]);
    expect(rest).toBe("");
  });

  it("tolerates \\r\\n line endings", () => {
    const { frames } = parseFrames("id: 1\r\nevent: plan_ready\r\ndata: {}\r\n\r\n");

    expect(frames).toEqual([{ id: "1", event: "plan_ready", data: "{}" }]);
  });
});