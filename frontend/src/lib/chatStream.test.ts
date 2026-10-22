import { describe, expect, it } from "vitest";
import { parseSseBuffer } from "./chatStream";

/** The SSE framing is parsed by hand (EventSource can't POST or send an auth
 * header), and the bug this class of code always has is mishandling a frame
 * split across two network chunks. That's what most of these cover. */

describe("parseSseBuffer", () => {
  it("parses a complete event", () => {
    const { events, rest } = parseSseBuffer('event: status\ndata: {"message":"hi"}\n\n');
    expect(events).toEqual([{ event: "status", data: '{"message":"hi"}' }]);
    expect(rest).toBe("");
  });

  it("parses several events from one chunk", () => {
    const buffer =
      'event: tool\ndata: {"tool":"a"}\n\n' + 'event: tool\ndata: {"tool":"b"}\n\n';
    const { events } = parseSseBuffer(buffer);
    expect(events.map((e) => e.data)).toEqual(['{"tool":"a"}', '{"tool":"b"}']);
  });

  it("holds back an incomplete frame as the remainder", () => {
    // A chunk that ends mid-frame must not be parsed — half a JSON payload
    // would be dropped by the caller's JSON.parse and the event lost.
    const { events, rest } = parseSseBuffer('event: message\ndata: {"partial":');
    expect(events).toEqual([]);
    expect(rest).toBe('event: message\ndata: {"partial":');
  });

  it("reassembles a frame split across two chunks", () => {
    const first = parseSseBuffer('event: message\ndata: {"a":1');
    expect(first.events).toEqual([]);
    const second = parseSseBuffer(first.rest + "}\n\n");
    expect(second.events).toEqual([{ event: "message", data: '{"a":1}' }]);
    expect(second.rest).toBe("");
  });

  it("keeps a trailing complete event and a following partial apart", () => {
    const { events, rest } = parseSseBuffer(
      'event: tool\ndata: {"tool":"a"}\n\nevent: message\ndata: {"b"'
    );
    expect(events).toEqual([{ event: "tool", data: '{"tool":"a"}' }]);
    expect(rest).toBe('event: message\ndata: {"b"');
  });

  it("defaults to the message event when no event line is present", () => {
    const { events } = parseSseBuffer('data: {"x":1}\n\n');
    expect(events).toEqual([{ event: "message", data: '{"x":1}' }]);
  });

  it("joins multi-line data payloads", () => {
    const { events } = parseSseBuffer("event: message\ndata: line one\ndata: line two\n\n");
    expect(events[0].data).toBe("line one\nline two");
  });

  it("ignores a frame with no data line", () => {
    // A comment/keepalive frame carries no data and must not surface as an
    // event with an empty payload.
    const { events } = parseSseBuffer(": keepalive\n\n");
    expect(events).toEqual([]);
  });

  it("returns nothing for an empty buffer", () => {
    expect(parseSseBuffer("")).toEqual({ events: [], rest: "" });
  });

  it("tolerates extra whitespace around values", () => {
    const { events } = parseSseBuffer('event:   tool   \ndata:    {"tool":"a"}   \n\n');
    expect(events).toEqual([{ event: "tool", data: '{"tool":"a"}' }]);
  });
});
