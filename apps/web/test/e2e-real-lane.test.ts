// @vitest-environment node
import { existsSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { Page } from "@playwright/test";
import type { UserConfig } from "vite";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import stubConfig from "../e2e/playwright.config";
import realConfig from "../e2e/playwright.real.config";
import { expires, same, setCookieNames, tamperOneByte } from "../e2e/support/real/cookies";
import { auditSliceSql } from "../e2e/support/real/failureArtefacts";
import { completeMfa, submitPassword } from "../e2e/support/real/signIn";
import { claimFrom, parseUsers } from "../e2e/support/real/stack";

/**
 * E09-Q02 (#293) PR 2 (#2490): the real lane's wiring, pinned where a slip would not fail a spec.
 * The two lanes never run each other's specs; the real lane keeps no trace, video or screenshot
 * (they would hold real session values in files the upload's secret check cannot read); the
 * clock-moving specs run alone; the proxy is loopback-only; the helpers never hand out a value.
 */
describe("the real lane's Playwright config", () => {
  it("runs only *.real.ts, which the stub lane's default *.spec.ts pattern never matches", () => {
    expect(realConfig.testMatch).toBe("**/*.real.ts");
    expect(stubConfig.testMatch).toBeUndefined();
  });

  it("keeps no trace, video or screenshot and retries nothing", () => {
    expect(realConfig.use).toMatchObject({ trace: "off", video: "off", screenshot: "off" });
    expect(realConfig.retries).toBe(0);
    expect(realConfig.forbidOnly).toBe(true);
  });

  it("runs sign-in specs on two workers and the @clock specs alone, after them", () => {
    const projects = (realConfig.projects ?? []).map((p) => ({
      name: p.name,
      workers: p.workers,
      grep: String(p.grep),
      grepInvert: String(p.grepInvert),
      dependencies: p.dependencies,
    }));
    expect(projects).toEqual([
      {
        name: "real",
        workers: 2,
        grep: "undefined",
        grepInvert: "/@clock/u",
        dependencies: undefined,
      },
      {
        name: "real-clock",
        workers: 1,
        grep: "/@clock/u",
        grepInvert: "undefined",
        dependencies: ["real"],
      },
    ]);
  });

  it("starts its own preview of dist/ with the proxy config, never another process's", () => {
    const server = realConfig.webServer;
    if (server === undefined || Array.isArray(server)) throw new Error("one webServer");
    expect(server.command).toMatch(/^npx vite preview -c e2e\/vite\.real\.config\.ts /u);
    expect(server.reuseExistingServer).toBe(false);
  });
});

describe("vite.real.config.ts", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("proxies /api/v1 and its WebSocket to the API with the prefix stripped", async () => {
    vi.stubEnv("CV_E2E_REAL_API", "http://127.0.0.1:15800");
    // `mergeConfig` types its result as a plain record: read it as the config it is
    const config = (await import("../e2e/vite.real.config")).default as UserConfig;
    const proxy = config.preview?.proxy?.["/api/v1"];
    if (proxy === undefined || typeof proxy === "string") throw new Error("an options proxy");
    expect(proxy.target).toBe("http://127.0.0.1:15800");
    expect(proxy.ws).toBe(true);
    expect(proxy.rewrite?.("/api/v1/auth/login")).toBe("/auth/login");
    expect(proxy.rewrite?.("/api/v1/ws")).toBe("/ws");
    expect(proxy.rewrite?.("/api/v1")).toBe("/");
    expect(proxy.rewrite?.("/api/v10/x")).toBe("/api/v10/x");
    expect(config.preview?.strictPort).toBe(true);
  });

  it.each(["https://127.0.0.1:8000", "http://10.0.0.5:8000", "http://api.example.test:8000"])(
    "refuses %s: the API is a loopback http origin",
    async (api) => {
      vi.stubEnv("CV_E2E_REAL_API", api);
      await expect(import("../e2e/vite.real.config")).rejects.toThrow(/loopback origin/u);
    },
  );
});

describe("the fixture users", () => {
  let dir: string;
  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "cv-real-lane-"));
  });
  afterEach(() => rmSync(dir, { recursive: true, force: true }));

  it("reads the users file the lane writes", () => {
    const text = JSON.stringify([{ username: "e2e-1a2b3c4d-1", totp_file: "/run/cv/e2e-1.totp" }]);
    expect(parseUsers(text)).toEqual([
      { username: "e2e-1a2b3c4d-1", totpFile: "/run/cv/e2e-1.totp" },
    ]);
  });

  it.each([
    ["an empty list", "[]", /non-empty JSON array/u],
    ["a name outside the grammar", '[{"username":"Ann O\'Neil","totp_file":"/x"}]', /username/u],
    ["a relative seed path", '[{"username":"ann","totp_file":"x.totp"}]', /absolute/u],
  ])("refuses %s", (_what, text, message) => {
    expect(() => parseUsers(text)).toThrow(message);
  });

  it("gives each claim a user no earlier claim got, and refuses once all are claimed", () => {
    const claims = join(dir, "claims");
    expect([claimFrom(["a", "b"], claims), claimFrom(["a", "b"], claims)]).toEqual(["a", "b"]);
    expect(readdirSync(claims).sort()).toEqual(["0", "1"]);
    expect(() => claimFrom(["a", "b"], claims)).toThrow(/all 2 fixture users are claimed/u);
    expect(existsSync(join(claims, "2"))).toBe(false);
  });
});

describe("the cookie helpers", () => {
  const headers = [
    { name: "content-type", value: "application/json" },
    {
      name: "set-cookie",
      value:
        'cv_refresh=""; expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; Max-Age=0; Path=/api/v1/auth; SameSite=strict; Secure\n__Host-cv_csrf=x; Max-Age=2592000; Path=/; SameSite=strict; Secure',
    },
  ];

  it("names what Set-Cookie sets, and tells an expiry from a set", () => {
    expect(setCookieNames(headers)).toEqual(["cv_refresh", "__Host-cv_csrf"]);
    expect(expires(headers, "cv_refresh")).toBe(true);
    expect(expires(headers, "__Host-cv_csrf")).toBe(false);
    expect(expires(headers, "cv_session")).toBe(false);
  });

  it("tampers exactly one character, and compares without handing a value out", () => {
    for (const value of ["abcdef0123456789", "AAAA", "x"]) {
      const tampered = tamperOneByte(value);
      expect(tampered).toHaveLength(value.length);
      expect([...tampered].filter((c, i) => c !== value[i])).toHaveLength(1);
    }
    expect(same("a", "a")).toBe(true);
    expect(same("a", "b")).toBe(false);
    expect(same(undefined, undefined)).toBe(false);
  });
});

describe("the audit slice", () => {
  const since = new Date("2026-10-30T16:00:00.000Z");
  const id = "18bc2887-37b0-42e9-9c6a-7a01419e5ac4";

  it("reads the test's users and correlation ids since it began, no state columns", () => {
    const sql = auditSliceSql(since, ["e2e-1a2b3c4d-1"], [id]);
    expect(sql).toContain("a.event_ts >= '2026-10-30T16:00:00.000Z'::timestamptz");
    expect(sql).toContain("ARRAY['e2e-1a2b3c4d-1']::text[]");
    expect(sql).toContain(`ARRAY['${id}']::uuid[]`);
    expect(sql).not.toMatch(/before_state|after_state|actor_ip/u);
    expect(auditSliceSql(since, [], [])).toContain("ARRAY[]::uuid[]");
  });

  it.each([
    ["a quote in a name", ["x' OR '1'='1"], []],
    ["a name outside the grammar", ["Ann"], []],
    ["an id that is not a UUID", [], ["1; DROP TABLE users"]],
  ])("refuses %s before building any SQL", (_what, users, ids) => {
    expect(() => auditSliceSql(since, users, ids)).toThrow();
  });
});

describe("the sign-in helpers' waits for an answer", () => {
  // A `waitForResponse` nobody awaits rejects, unhandled, when the page closes (the runner sets no
  // action timeout): that error would bury the failure that left it pending.
  const unhandled: unknown[] = [];
  const record = (reason: unknown): void => {
    unhandled.push(reason);
  };
  beforeEach(() => {
    unhandled.length = 0;
    process.on("unhandledRejection", record);
  });
  afterEach(() => {
    process.off("unhandledRejection", record);
  });

  /** A response wait that settles only when the test closes the "page", as a closing page does. */
  function pendingWait(): { wait: Promise<never>; closePage: () => void } {
    let reject: (reason: Error) => void = () => undefined;
    const wait = new Promise<never>((_resolve, rejectWith) => {
      reject = rejectWith;
    });
    return { wait, closePage: () => reject(new Error("the page closed")) };
  }

  /** One turn of the event loop: Node reports an unhandled rejection before it ends. */
  const turn = (): Promise<void> => new Promise((resolve) => setImmediate(resolve));

  it("completeMfa fails with the in-page fetch's error and leaves no wait unhandled", async () => {
    const { wait, closePage } = pendingWait();
    const page = {
      waitForResponse: () => wait,
      evaluate: () => Promise.reject(new Error("the fetch failed")),
    } as unknown as Page;
    await expect(completeMfa(page, "handle", "123456")).rejects.toThrow("the fetch failed");
    closePage();
    await turn();
    expect(unhandled).toEqual([]);
  });

  it("submitPassword fails with the form's error and leaves no wait unhandled", async () => {
    const { wait, closePage } = pendingWait();
    const field = { fill: () => Promise.reject(new Error("the field is gone")) };
    const page = {
      waitForResponse: () => wait,
      getByLabel: () => field,
      getByRole: () => ({ click: () => Promise.resolve() }),
    } as unknown as Page;
    const user = { username: "e2e-1a2b3c4d-1", seed: () => "" };
    await expect(submitPassword(page, user, "a-password")).rejects.toThrow("the field is gone");
    closePage();
    await turn();
    expect(unhandled).toEqual([]);
  });
});
