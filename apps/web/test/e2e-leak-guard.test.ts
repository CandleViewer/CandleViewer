// @vitest-environment node
import type { Page } from "@playwright/test";
import { describe, expect, it } from "vitest";
import { watchForLeaks } from "../e2e/support/api";

/**
 * E09-Q02 (#293), #5061's security look L2: `watchForLeaks` checks response bodies only, and fails
 * closed. A body it cannot read fails the flush (so "read nothing" never passes as "found nothing");
 * a redirect, which has no body, is passed over. Its flush first waits for the page's `/api/v1/`
 * requests to finish or fail, and fails on one still unsettled at its bound. A browser loses a body,
 * or a request, only when a navigation lands at the wrong moment, which a test cannot pick, so this
 * drives the guard with a stand-in page.
 */
type Listener = (request: unknown) => void;
type PageEvent = "request" | "requestfinished" | "requestfailed";

function fakePage() {
  const listeners = new Map<string, Listener>();
  const page = {
    on: (event: string, cb: Listener) => {
      listeners.set(event, cb);
    },
  } as unknown as Page;
  const emit = (event: PageEvent, request: unknown): void => listeners.get(event)?.(request);
  /** A request the page has started, which `finish` or `fail` settles (one object for all three, as Playwright's). */
  const start = (path = "/api/v1/probe?x=1") => {
    let status = 0;
    let body: string | Error = new Error("no response yet");
    const request = {
      method: () => "GET",
      url: () => `http://127.0.0.1:4173${path}`,
      response: async () => ({
        status: () => status,
        text: async () => {
          if (body instanceof Error) throw body;
          return body;
        },
      }),
    };
    emit("request", request);
    return {
      finish: (answered: number, text: string | Error): void => {
        status = answered;
        body = text;
        emit("requestfinished", request);
      },
      fail: (): void => emit("requestfailed", request),
    };
  };
  /** A request that finishes at once. */
  const finish = (status: number, body: string | Error): void => start().finish(status, body);
  return { page, start, finish };
}

describe("watchForLeaks", () => {
  it("passes when every body was read and none holds a forbidden value", async () => {
    const { page, finish } = fakePage();
    const guard = watchForLeaks(page, ["secret-value"]);
    finish(200, '{"ok":true}');
    finish(204, "");
    await expect(guard.flush()).resolves.toBeUndefined();
  });

  it("fails on a forbidden value, naming its length and never the value", async () => {
    const { page, finish } = fakePage();
    const guard = watchForLeaks(page, ["secret-value"]);
    finish(200, '{"echo":"secret-value"}');
    const error = await guard.flush().catch((e: unknown) => e as Error);
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toContain("leaked a 12-char value");
    expect((error as Error).message).not.toContain("secret-value");
  });

  it("fails closed on a body it could not read, naming the path without its query", async () => {
    const { page, finish } = fakePage();
    const guard = watchForLeaks(page, ["secret-value"]);
    finish(200, new Error("No resource with given identifier found"));
    await expect(guard.flush()).rejects.toThrow(
      "GET /api/v1/probe (200): its body was not read, so not checked",
    );
  });

  it("passes over a redirect, which has no body", async () => {
    const { page, finish } = fakePage();
    const guard = watchForLeaks(page, ["secret-value"]);
    finish(302, new Error("Response body is unavailable for redirect responses"));
    await expect(guard.flush()).resolves.toBeUndefined();
  });

  it("fails closed on the API's 304, whose cached body it cannot read, not on a static file's", async () => {
    const { page, start } = fakePage();
    const guard = watchForLeaks(page, ["secret-value"]);
    const unreadable = new Error("Response body is unavailable for redirect responses");
    start("/assets/index-abc123.js").finish(304, unreadable); // the SPA's own build, revalidated
    await expect(guard.flush()).resolves.toBeUndefined();
    start().finish(304, unreadable);
    await expect(guard.flush()).rejects.toThrow("GET /api/v1/probe (304): its body was not read");
  });

  it("refuses an empty forbidden value, which every body contains", () => {
    expect(() => watchForLeaks(fakePage().page, ["x", ""])).toThrow(/empty forbidden value/u);
  });

  it("waits for an API request still in flight at the flush, then checks its body", async () => {
    const { page, start } = fakePage();
    const guard = watchForLeaks(page, ["secret-value"]);
    const request = start();
    const flushed = guard.flush();
    request.finish(200, '{"echo":"secret-value"}');
    await expect(flushed).rejects.toThrow("leaked a 12-char value");
  });

  it("passes over a request that failed, which delivered no body", async () => {
    const { page, start } = fakePage();
    const guard = watchForLeaks(page, ["secret-value"]);
    start().fail();
    await expect(guard.flush()).resolves.toBeUndefined();
  });

  it("fails closed on an API request still unsettled at the bound, naming it", async () => {
    const { page, start } = fakePage();
    const guard = watchForLeaks(page, ["secret-value"], { settleMs: 50 });
    start("/api/v1/health/live");
    await expect(guard.flush()).rejects.toThrow("GET /api/v1/health/live");
  });

  it("does not wait for a request outside /api/v1/, such as a shared worker's script", async () => {
    const { page, start } = fakePage();
    const guard = watchForLeaks(page, ["secret-value"], { settleMs: 50 });
    start("/assets/wsWorker.js");
    await expect(guard.flush()).resolves.toBeUndefined();
  });
});
