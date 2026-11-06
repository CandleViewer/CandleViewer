import { readFileSync, statSync } from "node:fs";
import { isAbsolute, join } from "node:path";
import type { Page } from "@playwright/test";
import { CSRF_COOKIE } from "../support/real/cookies";
import { completeMfaByForm, submitPassword } from "../support/real/signIn";
import { serverClock } from "../support/serverClock";
import type { StubRole } from "./harness";

// E49-Q02 (#1336) run 2, tier B: what a session reads from the run directory
// `tools/qa/explore_stack.sh` made (docs/qa/e49-exploratory-harness.md §2): the shared password, one
// TOTP seed per role and the API's test clock. Values are read from the files when a sign-in needs
// them and go only into the page's own form: nothing here returns, logs or prints one.

/** The users' prefix the stack printed (`explore-<6 hex>`): the run directory does not hold it. */
const PREFIX = /^explore-[0-9a-f]{6}$/u;

export interface SeededStack {
  readonly username: (role: StubRole) => string;
  /** Signs `page` in as `role` through SCR-001 and SCR-002; the answer statuses only. */
  readonly signIn: (
    page: Page,
    role: StubRole,
  ) => Promise<{ passwordStatus: number; mfaStatus: number }>;
}

/** The stack named by `CV_EXPLORE_RUN_DIR` and `CV_EXPLORE_USER_PREFIX` (messages name no value). */
export function seededStack(env: NodeJS.ProcessEnv = process.env): SeededStack {
  const dir = env["CV_EXPLORE_RUN_DIR"] ?? "";
  if (!isAbsolute(dir)) throw new Error("CV_EXPLORE_RUN_DIR must be the stack's absolute run path");
  if ((statSync(dir).mode & 0o077) !== 0) throw new Error("the run directory must be mode 0700");
  const prefix = env["CV_EXPLORE_USER_PREFIX"] ?? "";
  if (!PREFIX.test(prefix)) throw new Error("CV_EXPLORE_USER_PREFIX must be explore-<6 hex>");
  const clock = serverClock(join(dir, "clock", "offset"));
  const read = (name: string): string => readFileSync(join(dir, name), "ascii").trim();
  const username = (role: StubRole): string => `${prefix}-${role}`;
  return {
    username,
    async signIn(page, role) {
      // Playwright writes a `fill(...)` call, value included, into the error of a step that fails,
      // so any failure of the sign-in is rethrown with a message that names the role alone.
      try {
        await page.goto("/login");
        const user = { username: username(role), seed: () => read(`${role}.totp`) };
        const step = await submitPassword(page, user, read("password"));
        if (!step.mfaRequired) return { passwordStatus: step.status, mfaStatus: 0 };
        clock.advance(30); // one code per step per user (A06): a fresh step for every sign-in
        const mfa = await completeMfaByForm(page, clock.totpAt(user.seed()));
        return { passwordStatus: step.status, mfaStatus: mfa.status };
      } catch {
        throw new Error(`sign-in as ${role} failed`);
      }
    },
  };
}

/** One privileged call: who may make it; any other role must be refused. */
export interface Probe {
  readonly method: "GET" | "POST" | "PUT";
  readonly path: string;
  readonly body?: unknown;
  readonly allow: readonly StubRole[];
}

/**
 * Makes each probe from the page with the bearer a cookie refresh issues: the bearer stays inside
 * the page, only statuses come back. Writes carry the CSRF header, as the SPA sends them.
 */
export async function callAs(
  page: Page,
  probes: readonly Probe[],
): Promise<{ refresh: number; statuses: readonly number[] }> {
  return page.evaluate(
    async ({ csrfName, list }) => {
      const pair = document.cookie
        .split(";")
        .map((part) => part.trim())
        .find((part) => part.startsWith(`${csrfName}=`));
      const csrf = pair?.slice(csrfName.length + 1) ?? "";
      const head: Record<string, string> = csrf === "" ? {} : { "X-CSRF-Token": csrf };
      const res = await fetch("/api/v1/auth/refresh", { method: "POST", headers: head });
      const body = (await res.json().catch(() => ({}))) as { tokens?: { access_token?: unknown } };
      const bearer = body.tokens?.access_token;
      if (typeof bearer !== "string") return { refresh: res.status, statuses: [] };
      const statuses: number[] = [];
      for (const p of list) {
        const init: RequestInit = {
          method: p.method,
          headers: {
            ...head,
            Authorization: `Bearer ${bearer}`,
            "Content-Type": "application/json",
          },
          ...(p.body === undefined ? {} : { body: JSON.stringify(p.body) }),
        };
        statuses.push((await fetch(p.path, init)).status);
      }
      return { refresh: res.status, statuses };
    },
    { csrfName: CSRF_COOKIE, list: probes.map((p) => ({ ...p, allow: [...p.allow] })) },
  );
}

/** One probe's status judged for `role`: a refused privileged call is `ok`, a 2xx or 5xx `suspect`. */
export function judgeProbe(
  probe: Probe,
  role: StubRole,
  status: number,
): "ok" | "suspect" | "info" {
  if (probe.allow.includes(role)) return "info";
  if (status === 401 || status === 403 || status === 404) return "ok";
  return (status >= 200 && status < 300) || status >= 500 ? "suspect" : "info";
}
