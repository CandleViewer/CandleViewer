// E17-Q04 (#569): helpers of the E17 transport-state specs. The driver is the E08-Q05 fake gateway (`wsHarness.ts`) in
// front of the REAL web client, on the shipped bundle (`vite preview` of `dist/`): engine, codec and close policy run
// unchanged, and `ws-harness.spec.ts` checks `dist/` carries no harness code. What is read here is merged code: the
// chip (`ConnectionStatus.tsx`), the region (`ConnectionRegion.tsx`, `connectionRegion.ts`), the shell announcer.
// A wait is an event (a locator, a poll of the harness's frame log) bounded by the test timeout, never a sleep
// (03-testing-strategy.md section 14).
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { AXE_GATE_TAGS } from "../a11y/tags";
import { stubSession } from "../support/api";
import { startWsHarness, type Heartbeat, type WsHarness } from "../support/wsHarness";

/** `expect` bounded by the 30 s test timeout rather than the 5 s default; no test reads a duration from it. */
export const patient = expect.configure({ timeout: 25_000 });

/** The title tag of the release regression pack (`qa/plans/e17-regression-pack.md`). */
export const PACK = "@e17-regression";
/** The nightly real-time measurements: never a PR gate, never in the pack. */
export const REALTIME = "@e17-realtime";

/** What a test guards, as the pack cites it: a C-rule, a D02 row, a story or AC. The audit tool reads these. */
export function covers(...ids: string[]): void {
  test.info().annotations.push({ type: "covers", description: ids.join("; ") });
}

// --- locators ---------------------------------------------------------------------------------------------------
/** CMP-076, the top bar's chip: one native button named "Connection: <word>…"; its `data-status` is the five-value union (E17-D02 section 3). */
export const chip = (page: Page): Locator => page.getByRole("button", { name: /^Connection: / });
/** CMP-077, the SCR-152 connection region: a non-modal `region` named "Connection" in the banner slot. */
export const region = (page: Page): Locator =>
  page.getByRole("region", { name: "Connection", exact: true });
export const retryNow = (page: Page): Locator =>
  region(page).getByRole("button", { name: "Retry now" });
export const signIn = (page: Page): Locator =>
  region(page).getByRole("button", { name: "Sign in" });
/** The shell announcer's assertive node: its one message, or none (`announcer.tsx`). An attribute selector: the node has no role to query. */
export const assertive = (page: Page): Locator => page.locator('[aria-live="assertive"] > p');
/** The status bar's connection word (`StatusBar.tsx`). */
export const statusWord = (page: Page): Locator =>
  page.getByText(/^Connection: (live|connecting|reconnecting|offline)$/);

// --- words, as `connectionRegion.ts` writes them (E17-D02 sections 10 and 11) -------------------------------------
export const SAID = {
  disconnected:
    "Disconnected. New orders off. Cancel and close still work, confirmed over the server. Exchange-side stops still protect open positions.",
  retryStopped:
    "Offline — retry stopped. New orders off. Cancel and close still work, confirmed over the server.",
  sessionEnded: "Your access was removed — contact the owner.",
  killSwitch: "Order entry off — trading frozen by the owner. Cancel still works.",
  shutdown:
    "Order entry off — backend restarting. Cancel and close still work; exchange-side stops still protect open positions; app-managed rules are paused.",
  systemUnknown:
    "Order entry off — kill-switch status unknown until the server reports it. Cancel and close still work.",
} as const;

// --- what the gateway can send (23 sections 4.4, 8.4, 15.9) --------------------------------------------------------
export const KILL_ENGAGED = {
  kind: "kill_switch",
  kill_switch: { engaged: true, scope: "global", exchange_account_ids: [], reason: "e2e" },
} as const;
export const SHUTDOWN_NOTICE = {
  kind: "shutdown_notice",
  closing_in_ms: 5_000,
  expected_downtime_ms: 20_000,
  message: "restart for the next release",
} as const;
/** A fatal close the client must not retry (D02 row 6). A page cannot send 1002, so 4400 stands for the class. */
export const BYE_FATAL = {
  code: 4400,
  reason: "bad_client",
  message: "repeated malformed frames",
  reconnect: false,
} as const;
/** The account's access ended (D02 row 21). */
export const BYE_SESSION_ENDED = {
  code: 4403,
  reason: "user_disabled",
  message: "user disabled",
  reconnect: false,
} as const;
/** 23 section 8.4 step 3: a slow consumer gets this `bye` and close 4429, and may come back. */
export const BYE_SLOW_CONSUMER = {
  code: 4429,
  reason: "slow_consumer",
  message: "the connection could not keep up",
  reconnect: true,
  retry_after_ms: 1_000,
} as const;

// --- opening the workspace -----------------------------------------------------------------------------------------
export interface OpenOptions {
  /** Keep the first socket in its first connect: no `welcome` until `harness.release("hello")` (D02 row 1). */
  readonly hold?: boolean;
  /**
   * Fake the PAGE's clock before the page loads, set to the real time (`setSystemTime` puts the fake timers in and
   * sets them), so a test can move it with `fastForward`. The shared worker keeps the real clock (Q04-S01).
   */
  readonly clock?: boolean;
  /** 13.3 floors (ping every 1 000 ms): `settle()` waits on those pings. */
  readonly heartbeat?: Heartbeat;
  /** Scheme and host when the page has no `baseURL`. */
  readonly origin?: string;
}

/** An owner session on the fixture gateway, `/terminal` open and, unless held, the first `auth_ok` answered. */
export async function openWorkspace(page: Page, options: OpenOptions = {}): Promise<WsHarness> {
  await stubSession(page, { role: "owner" });
  if (options.clock === true) await page.clock.setSystemTime(Date.now());
  const harness = await startWsHarness(page, options.heartbeat);
  if (options.hold === true) harness.hold("hello");
  await page.goto(`${options.origin ?? ""}/terminal`);
  if (options.hold === true) await patient.poll(() => harness.connections()).toBe(1);
  else await patient.poll(() => harness.authenticated()).toBe(1);
  return harness;
}

/** 13.3's floor: a 1 s ping keeps `settle` short without moving 9.2. */
export const FAST_HEARTBEAT: Heartbeat = { interval_ms: 1_000, timeout_ms: 5_000 };

/**
 * A barrier that is an event, not a sleep: two client `ping`s after now. Whatever the client sends because of what the
 * test just did (a `sub`, a `resync`, a new socket) is in `frames` by then. Needs `FAST_HEARTBEAT` and a live socket.
 */
export async function settle(harness: WsHarness): Promise<void> {
  const pings = (): number => harness.frames.filter((f) => f.frame.t === "ping").length;
  const from = pings();
  await patient.poll(pings).toBeGreaterThanOrEqual(from + 2);
}

/** Marks the announced node: a second announcement replaces it (a new React key) and loses the mark. */
export async function markAnnounced(page: Page): Promise<void> {
  await assertive(page).evaluate((el) => el.setAttribute("data-e2e-said", "1"));
}
export const stillTheSameAnnouncement = (page: Page): Promise<void> =>
  expect(assertive(page)).toHaveAttribute("data-e2e-said", "1");

/** The chip's content fades in once per change (`useCrossFade`): a scan before it ends reads half-faded text. */
export async function chipSettled(page: Page): Promise<void> {
  const fade = chip(page).locator("[data-fade]"); // the cross-fade wrapper has no role or label to query
  await patient.poll(() => fade.evaluate((el) => getComputedStyle(el).opacity)).toBe("1");
}

/** "Last data 00:12 ago" (E17-D02 section 10 B), in seconds; `formatAge` writes "1:05:03" past an hour. */
export function lastDataAgeSeconds(text: string | null): number {
  const m = /Last data (?:(\d+):)?(\d\d):(\d\d) ago/.exec(text ?? "");
  if (m === null) throw new Error(`no "Last data … ago" in: ${text ?? "(none)"}`);
  return Number(m[1] ?? 0) * 3600 + Number(m[2]) * 60 + Number(m[3]);
}

// --- axe: zero violations of any impact (AC 4) ------------------------------------------------------------------------
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "../../../..");
/** The ruled pins of the audit tool: a waiver is an `axe-waiver<TAB>rule-id<TAB>ruling` line there, and only there. */
export const PINS_REL = "qa/plans/_tools/e17_q04_ruled_pins.txt";
export function axeWaivers(): readonly string[] {
  return readFileSync(join(ROOT, PINS_REL), "utf8")
    .split("\n")
    .filter((line) => line.startsWith("axe-waiver\t"))
    .map((line) => line.split("\t")[1] ?? "");
}

/**
 * Every violation of the tagged scan, of any impact, as `id (impact): help`, less the ruled waivers. The scan is the
 * gate's own (`AXE_GATE_TAGS`); `seriousAxe` stays as it is (other specs pin it).
 */
export async function strictAxe(page: Page): Promise<string[]> {
  const res = await new AxeBuilder({ page }).withTags([...AXE_GATE_TAGS]).analyze();
  const waived = axeWaivers();
  return res.violations
    .filter((v) => !waived.includes(v.id))
    .map((v) => `${v.id} (${v.impact ?? "n/a"}): ${v.help}`);
}

// --- C12's "no REST round-trip" -------------------------------------------------------------------------------------
/**
 * The paths a client could poll to learn the kill switch's state (22: `/trading/kill-switch`, `/risk/summary`'s lockout
 * state, `/admin/health`, which backs the `system` topic). The shell's liveness probe (`/health/live`) carries none.
 */
export const WOULD_BE_A_POLL = /\/api\/v1\/(trading\/kill-switch|risk\/summary|admin\/health)/;
export function watchPolls(page: Page): readonly string[] {
  const seen: string[] = [];
  page.on("request", (r) => {
    if (WOULD_BE_A_POLL.test(r.url())) seen.push(`${r.method()} ${new URL(r.url()).pathname}`);
  });
  return seen;
}

/** The frame types the client sent on connection `n`, in order. */
export const sentTypes = (harness: WsHarness, n: number): string[] =>
  harness.frames.filter((f) => f.conn === n).map((f) => f.frame.t);

/** The `snap`s the gateway sent on `system`. */
export const systemSnaps = (harness: WsHarness): readonly Readonly<Record<string, unknown>>[] =>
  harness.sent.filter((f) => f.t === "snap" && f["ch"] === "system");
