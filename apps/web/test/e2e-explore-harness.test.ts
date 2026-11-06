// @vitest-environment node
import { chmodSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { Page } from "@playwright/test";
import { afterEach, describe, expect, it, vi } from "vitest";
import { stubWithGateway, tabSweep, type Observation } from "../e2e/exploratory/harness";
import { callAs, judgeProbe, seededStack, type Probe } from "../e2e/exploratory/seededStack";

/**
 * E49-Q02 (#1336) run 2: the exploratory harness's helpers, pinned here because no CI job runs the
 * sessions themselves. A Tab sweep notes its cycle and any trap; the socket stub's refresh answer is
 * the one a page gets; tier B keeps no recording and refuses a run directory it cannot trust.
 */

/** A page whose focus walks `stops` one per Tab press (what `focused` reads from the page). */
function focusPage(stops: readonly string[]): Page {
  let at = -1;
  return {
    keyboard: { press: async () => void (at += 1) },
    evaluate: async () => stops[Math.min(at, stops.length - 1)],
  } as unknown as Page;
}

function sweepLog(): {
  note: (o: Omit<Observation, "charter">) => void;
  notes: Omit<Observation, "charter">[];
} {
  const notes: Omit<Observation, "charter">[] = [];
  return { note: (o) => void notes.push(o), notes };
}

describe("tabSweep", () => {
  it("records the cycle back to the first stop and no trap as ok", async () => {
    const log = sweepLog();
    const s = await tabSweep(focusPage(["#1 a", "#2 b", "#3 c", "#1 a"]), 60, {
      log,
      route: "/x",
      role: "owner",
    });
    expect([s.cycle, s.trap, s.unique]).toEqual([3, null, 3]);
    const kb = log.notes.filter((n) => n.oracle.startsWith("O-KB"));
    expect(kb.map((n) => [n.oracle, n.result])).toEqual([
      ["O-KB.1", "ok"],
      ["O-KB.2", "ok"],
    ]);
  });

  it("calls focus held on one stop a trap", async () => {
    const s = await tabSweep(focusPage(["#1 a", "#2 b", "#2 b", "#2 b", "#2 b"]), 5);
    expect(s.trap).toBe("held on #2 b for 3 presses");
    expect(s.cycle).toBeNull();
  });

  it("calls a loop that never reaches the first stop a trap, and notes it suspect", async () => {
    const log = sweepLog();
    const loop = ["#1 a", "#2 b", "#3 c", "#2 b", "#3 c", "#2 b", "#3 c"];
    const s = await tabSweep(focusPage(loop), 7, { log, route: "/x", role: "owner" });
    expect(s.trap).toBe("loop of 2 stops without the first");
    expect(log.notes.find((n) => n.oracle === "O-KB.1")?.result).toBe("suspect");
  });

  it("notes a sweep that never returns to the first stop as suspect, without calling it a trap", async () => {
    const log = sweepLog();
    const s = await tabSweep(focusPage(["#1 a", "#2 b", "#3 c"]), 3, {
      log,
      route: "/x",
      role: "o",
    });
    expect([s.cycle, s.trap]).toEqual([null, null]);
    expect(log.notes.find((n) => n.oracle === "O-KB.1")?.result).toBe("suspect");
  });

  it("notes a page with one focus stop as suspect even when it cycles", async () => {
    const log = sweepLog();
    const s = await tabSweep(focusPage(["#1 a", "#1 a"]), 5, { log, route: "/x", role: "o" });
    expect([s.cycle, s.unique, s.trap]).toEqual([1, 1, null]);
    expect(log.notes.find((n) => n.oracle === "O-KB.1")?.result).toBe("suspect");
  });

  it("notes a stop without a visible focus style under O-KB.2", async () => {
    const log = sweepLog();
    await tabSweep(focusPage(["#1 a", "#2 b (no ring)", "#1 a"]), 60, {
      log,
      route: "/x",
      role: "v",
    });
    expect(log.notes.find((n) => n.oracle === "O-KB.2")?.result).toBe("suspect");
  });
});

type Matcher = string | ((url: URL) => boolean);
type Handler = (route: unknown) => unknown;

describe("stubWithGateway (the ws fixture's wiring)", () => {
  it("leaves the socket stub's refresh answer last, with a value the socket client accepts", async () => {
    const routes: [Matcher, Handler][] = [];
    const sockets: string[] = [];
    const page = {
      route: async (m: Matcher, h: Handler) => void routes.push([m, h]),
      routeWebSocket: async (m: string) => void sockets.push(m),
      addInitScript: async () => undefined,
    } as unknown as Page;
    await stubWithGateway(page, "viewer");
    const hits = (path: string) =>
      routes.filter(([m]) =>
        typeof m === "string" ? m === `**${path}` : m(new URL(`http://127.0.0.1${path}`)),
      );
    const refresh = hits("/api/v1/auth/refresh");
    expect(refresh.length).toBe(2);
    let answer: { body?: string } = {};
    await refresh.at(-1)?.[1]({ fulfill: (o: { body?: string }) => void (answer = o) });
    const issued = (JSON.parse(answer.body ?? "{}") as { tokens?: { access_token?: string } })
      .tokens?.access_token;
    expect(issued?.length ?? 0).toBeGreaterThanOrEqual(20);
    expect(sockets).toEqual(["**/api/v1/ws"]);
    expect(hits("/api/v1/auth/sessions").length).toBe(1);
  });
});

describe("judgeProbe", () => {
  const read: Probe = { method: "GET", path: "/api/v1/admin/overview", allow: ["owner"] };
  it.each([
    ["viewer", 403, "ok"],
    ["manager", 401, "ok"],
    ["manager", 404, "ok"],
    ["viewer", 200, "suspect"],
    ["manager", 503, "suspect"],
    ["viewer", 422, "info"],
    ["owner", 200, "info"],
    ["owner", 403, "info"],
  ] as const)("%s answered %i is %s", (role, status, result) => {
    expect(judgeProbe(read, role, status)).toBe(result);
  });
});

describe("callAs", () => {
  it("hands back statuses only: the bearer and the answer bodies stay in the page", async () => {
    const bearer = "bearer-value-that-must-stay-in-the-page";
    const seen: string[] = [];
    const fetchStub = async (path: string, init?: RequestInit): Promise<Response> => {
      seen.push(`${init?.method ?? "GET"} ${path}`);
      return path.endsWith("/auth/refresh")
        ? new Response(JSON.stringify({ tokens: { access_token: bearer } }), { status: 200 })
        : new Response(JSON.stringify({ secret: bearer }), { status: 403 });
    };
    vi.stubGlobal("fetch", fetchStub);
    vi.stubGlobal("document", { cookie: "other=1; cv_csrf=tok" });
    const page = {
      evaluate: async (fn: (a: unknown) => unknown, arg: unknown) => fn(arg),
    } as unknown as Page;
    const probe: Probe = { method: "GET", path: "/api/v1/admin/overview", allow: ["owner"] };
    const got = await callAs(page, [probe, probe]);
    vi.unstubAllGlobals();
    expect(Object.keys(got).sort()).toEqual(["refresh", "statuses"]);
    expect(got.statuses).toEqual([403, 403]);
    expect(JSON.stringify(got)).not.toContain(bearer);
    expect(seen).toHaveLength(3);
  });
});

describe("tier B sign-in", () => {
  const made: string[] = [];
  afterEach(() => {
    for (const dir of made.splice(0)) rmSync(dir, { recursive: true, force: true });
  });
  const stack = (files: Record<string, string>) => {
    const dir = mkdtempSync(join(tmpdir(), "cv-explore-test-"));
    made.push(dir);
    chmodSync(dir, 0o700);
    for (const [name, value] of Object.entries(files)) writeFileSync(join(dir, name), value);
    return seededStack({ CV_EXPLORE_RUN_DIR: dir, CV_EXPLORE_USER_PREFIX: "explore-a1b2c3" });
  };

  it("rethrows a failed fill without the password the page's own error carried", async () => {
    const password = "throwaway-password-value-1";
    const field = {
      fill: async (v: string) =>
        v === password ? Promise.reject(new Error(`fill("${v}") timed out`)) : undefined,
    };
    const page = {
      goto: async () => undefined,
      waitForResponse: () => new Promise(() => undefined),
      getByLabel: () => field,
      getByRole: () => field,
    } as unknown as Page;
    const err = await stack({ password })
      .signIn(page, "owner")
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(Error);
    expect((err as Error).message).toBe("sign-in as owner failed");
    expect(JSON.stringify(err, Object.getOwnPropertyNames(err))).not.toContain(password);
  });

  it("names the role alone when a credential file is missing", async () => {
    const page = {
      goto: async () => undefined,
      waitForResponse: () => new Promise(() => undefined),
      getByLabel: () => ({ fill: async () => undefined }),
      getByRole: () => ({ click: async () => undefined }),
    } as unknown as Page;
    await expect(stack({}).signIn(page, "viewer")).rejects.toThrow(/^sign-in as viewer failed$/u);
  });
});

describe("tier B", () => {
  const made: string[] = [];
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
    for (const dir of made.splice(0)) rmSync(dir, { recursive: true, force: true });
  });

  it("runs only @tier-b sessions, records nothing and starts no server of its own", async () => {
    vi.stubEnv("CV_EXPLORE_RUN_DIR", "");
    const a = (await import("../e2e/exploratory/playwright.explore.config")).default;
    expect([a.grepInvert, a.use?.trace, a.webServer === undefined]).toEqual([
      /@tier-b/u,
      "on",
      false,
    ]);
    vi.resetModules();
    vi.stubEnv("CV_EXPLORE_RUN_DIR", "/run/cv-explore.x");
    const b = (await import("../e2e/exploratory/playwright.explore.config")).default;
    expect([b.grep, b.grepInvert, b.webServer]).toEqual([/@tier-b/u, undefined, []]);
    expect([b.use?.trace, b.use?.video, b.use?.screenshot]).toEqual(["off", "off", "off"]);
  });

  it("refuses a relative run directory, an open one and a malformed prefix, naming no value", () => {
    const dir = mkdtempSync(join(tmpdir(), "cv-explore-test-"));
    made.push(dir);
    const env = (over: Record<string, string>) => ({
      CV_EXPLORE_RUN_DIR: dir,
      CV_EXPLORE_USER_PREFIX: "explore-a1b2c3",
      ...over,
    });
    expect(() => seededStack(env({ CV_EXPLORE_RUN_DIR: "rel" }))).toThrow(/absolute run path$/u);
    for (const mode of [0o755, 0o750, 0o705, 0o701, 0o710]) {
      chmodSync(dir, mode);
      expect(() => seededStack(env({}))).toThrow("the run directory must be mode 0700");
    }
    chmodSync(dir, 0o700);
    expect(() => seededStack(env({ CV_EXPLORE_USER_PREFIX: "alice" }))).toThrow(
      "CV_EXPLORE_USER_PREFIX must be explore-<6 hex>",
    );
    expect(seededStack(env({})).username("viewer")).toBe("explore-a1b2c3-viewer");
  });
});
