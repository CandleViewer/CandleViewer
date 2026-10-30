// @vitest-environment node
import type { Page } from "@playwright/test";
import { describe, expect, it } from "vitest";
import { watchForLeaks } from "../e2e/support/api";

/**
 * E09-Q02 (#293), #5061's security look L2: `watchForLeaks` checks response bodies only, and fails
 * closed. A body it cannot read fails the flush (so "read nothing" never passes as "found nothing");
 * a redirect, which has no body, is passed over. A browser cannot make a body unreadable on demand
 * (a routed body is always readable), so this drives the guard with a stand-in page.
 */
type Finished = (request: unknown) => void;

function fakePage(): { page: Page; finish: (status: number, body: string | Error) => void } {
  let listener: Finished = () => undefined;
  const page = {
    on: (event: string, cb: Finished) => {
      if (event === "requestfinished") listener = cb;
    },
  } as unknown as Page;
  const finish = (status: number, body: string | Error): void =>
    listener({
      method: () => "GET",
      url: () => "http://127.0.0.1:4173/api/v1/probe?x=1",
      response: async () => ({
        status: () => status,
        text: async () => {
          if (body instanceof Error) throw body;
          return body;
        },
      }),
    });
  return { page, finish };
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

  it("refuses an empty forbidden value, which every body contains", () => {
    expect(() => watchForLeaks(fakePage().page, ["x", ""])).toThrow(/empty forbidden value/u);
  });
});
