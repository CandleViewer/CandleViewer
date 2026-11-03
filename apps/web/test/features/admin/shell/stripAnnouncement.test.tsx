/**
 * E42-S01 (#1022): the "Needs your action" strip is not live (E42-D03 §6 Keys), so the shell says a
 * new item once: polite, once per item (E42-D02:312; E42-D03-handoff Table 5), through the shell's
 * announcer and never a region of the area's own. The strip is read through the real store, a stubbed
 * `fetch` and fake timers; what the owner hears is the shell's polite region. The words are the pill's
 * own accessible name, so what is said is what Tab will read.
 */
import { act, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { adminReads, REREAD_MS } from "../../../../src/features/admin/overview/readStore";
import { AdminArea } from "../../../../src/features/admin/shell/AdminArea";
import {
  announce,
  clearAnnouncements,
  REGION_BUDGET_MS,
  ShellAnnouncer,
} from "../../../../src/features/app-shell/announcer";
import { InShellProvider } from "../../../../src/features/app-shell/ScreenRoot";
import { resetShellState, setShellState } from "../../../../src/shell/bootstrap/store";

const AT = "2026-10-22T14:02:11Z";

/** What the strip's two reads serve: the counts behind its items; `null` is a slice that errored. */
interface Served {
  readonly mfa: number | null;
  readonly expiring: number;
  readonly invalid: number;
  readonly tier: "recorded" | "unrecorded";
}
const NOTHING: Served = { mfa: 0, expiring: 0, invalid: 0, tier: "recorded" };
let served: Served;
/** A status other than 200 for a read, this test. */
let refused: { overview?: number; capacity?: number };
/** Capacity's answer is held until this settles, so its items arrive after the overview's. */
let capacityLate: Promise<void> | null;

// The items as their pills read them, in a DEMO session ("Attention:" first, the badge's word last).
const NO_MFA = "Attention: 1 active user without two-factor → Users";
const KEY_REJECTED = "Attention: 1 key rejected by Bybit → Accounts and keys DEMO";
const KEY_EXPIRES = "Attention: 1 key expires within 30 days → Accounts and keys DEMO";

function answerFor(read: "overview" | "capacity"): unknown {
  if (read === "capacity") {
    return { subaccounts: { status: "ok", generated_at: AT, tier_source: served.tier, used: 1 } };
  }
  const users =
    served.mfa === null
      ? { status: "error", generated_at: AT, detail: "users: read failed" }
      : { status: "ok", generated_at: AT, total: 9, active: 6, without_mfa: served.mfa };
  const accounts = {
    status: "ok",
    generated_at: AT,
    total: 1,
    keys_expiring_30d: served.expiring,
    keys_invalid: served.invalid,
  };
  return { generated_at: AT, users, accounts };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(Date.parse(AT));
  adminReads.reset();
  clearAnnouncements();
  served = NOTHING;
  refused = {};
  capacityLate = null;
  setShellState({ environment: "demo" }); // the accounts' items carry the session's badge
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const read = String(input).endsWith("/admin/overview") ? "overview" : "capacity";
      if (read === "capacity") await capacityLate;
      const status = refused[read] ?? 200;
      const body = status === 200 ? answerFor(read) : { code: "refused" };
      return new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
});
afterEach(() => {
  adminReads.reset();
  clearAnnouncements();
  resetShellState();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

/** The shell's announcer beside the area, which `show` mounts and unmounts alone. */
function Visit({ show = true }: { show?: boolean }) {
  return (
    <MemoryRouter>
      <InShellProvider>
        <ShellAnnouncer />
        <main tabIndex={-1}>{show ? <AdminArea routeId="R-301" owner="E18" /> : null}</main>
      </InShellProvider>
    </MemoryRouter>
  );
}

const flush = (ms = 0): Promise<void> =>
  act(async () => void (await vi.advanceTimersByTimeAsync(ms)));

/** The owner arrives: the area mounts and both strip reads are answered. */
async function arrive(first: Partial<Served> = {}): Promise<ReturnType<typeof render>> {
  served = { ...NOTHING, ...first };
  const view = render(<Visit />);
  await flush();
  return view;
}

const region = (politeness: "polite" | "assertive"): Element | null =>
  document.querySelector(`[aria-live="${politeness}"] p`);
const heard = (politeness: "polite" | "assertive" = "polite"): string | null =>
  region(politeness)?.textContent ?? null;
/** The polite region's write number: it moves whenever a line is written, even the same words. */
const writes = (): string | null => region("polite")?.getAttribute("data-seq") ?? null;
const pills = (): HTMLElement[] =>
  within(screen.getByRole("region", { name: "Needs your action" })).getAllByRole("link");

describe("a new strip item is said once, politely, through the shell's announcer", () => {
  it("says nothing for the items on the strip when the owner arrives", async () => {
    await arrive({ mfa: 1, expiring: 2, tier: "unrecorded" });
    expect(pills()).toHaveLength(3);
    expect(heard()).toBeNull();
    expect(heard("assertive")).toBeNull();
  });

  it("counts an item whose source answers after the others as part of the arrival", async () => {
    let answer!: () => void;
    capacityLate = new Promise<void>((resolve) => {
      answer = resolve;
    });
    await arrive({ mfa: 1, tier: "unrecorded" });
    expect(pills()).toHaveLength(1); // the overview's item; capacity has not answered yet
    answer();
    await flush();
    expect(pills()).toHaveLength(2); // the tier item joined the strip, still the arrival
    expect(heard()).toBeNull();
  });

  it("says a new item in the words its pill reads, once, on the polite region only", async () => {
    await arrive();
    served = { ...NOTHING, invalid: 1 };
    await flush(REREAD_MS);
    const [pill] = pills();
    expect(pill).toHaveAccessibleName(KEY_REJECTED);
    expect(heard()).toBe(KEY_REJECTED);
    expect(pill).toHaveAccessibleName(heard() ?? ""); // what is said is what Tab reads
    expect(heard("assertive")).toBeNull();
    // the shell's region, never one of the area's own
    expect(
      screen.getByRole("main").querySelector("[aria-live], [role='status'], [role='alert']"),
    ).toBeNull();
    const said = writes();
    await flush(REGION_BUDGET_MS * 2);
    expect(writes()).toBe(said); // once: nothing writes it again
  });

  it("says nothing more for the same items: the arrival's, a re-render, the re-read, a count that moved", async () => {
    const view = await arrive({ tier: "unrecorded" }); // an item the arrival holds, never said
    const tier = { tier: "unrecorded" } as const; // capacity is read once per entry, not re-read
    served = { ...NOTHING, ...tier, expiring: 1 };
    await flush(REREAD_MS);
    const once = writes();
    expect(heard()).toBe(KEY_EXPIRES); // the new item only: the arrival's item is not said with it
    await flush(REGION_BUDGET_MS * 2);
    expect(writes()).toBe(once);
    view.rerender(<Visit />);
    await flush(REREAD_MS); // the 30 s re-read answers the same items
    expect(writes()).toBe(once);
    served = { ...NOTHING, ...tier, expiring: 3 }; // a count moves on an item already there
    await flush(REREAD_MS);
    expect(pills()).toHaveLength(2);
    expect(pills()[0]).toHaveAccessibleName(
      "Attention: 3 keys expire within 30 days → Accounts and keys DEMO",
    );
    await flush(REGION_BUDGET_MS * 2);
    expect(writes()).toBe(once); // not a new item
    expect(heard()).toBe(KEY_EXPIRES);
  });

  it("says each of two new items from one read once, a polite line apart (E17-D02 §11)", async () => {
    await arrive();
    served = { ...NOTHING, mfa: 1, invalid: 1 };
    await flush(REREAD_MS);
    expect(heard()).toBe(NO_MFA);
    await flush(REGION_BUDGET_MS - 100); // one line per 5 s: the first is not cut
    expect(heard()).toBe(NO_MFA);
    await flush(100);
    expect(heard()).toBe(KEY_REJECTED);
    const last = writes();
    await flush(REREAD_MS * 2); // nothing says either again
    expect(writes()).toBe(last);
  });

  it("waits out another writer's polite line before its own", async () => {
    await arrive();
    await flush(REREAD_MS - 2_000);
    act(() => void announce("polite", "Admin · Users and roles · DEMO", "test:route"));
    served = { ...NOTHING, mfa: 1 };
    await flush(2_000); // the re-read lands 2 s after the other line
    expect(pills()).toHaveLength(1);
    expect(heard()).toBe("Admin · Users and roles · DEMO");
    await flush(REGION_BUDGET_MS - 2_000 - 100);
    expect(heard()).toBe("Admin · Users and roles · DEMO");
    await flush(100);
    expect(heard()).toBe(NO_MFA);
  });

  it("waits at most one budget for another writer's line, whatever the wall clock did", async () => {
    await arrive();
    act(() => void announce("polite", "Admin · Users and roles · DEMO", "test:route"));
    vi.setSystemTime(Date.now() - 3_600_000); // the clock is set back an hour after that line
    served = { ...NOTHING, mfa: 1 };
    act(() => adminReads.retry(["overview"], "test")); // a read now: the cycle reads by the clock
    await flush();
    expect(pills()).toHaveLength(1);
    expect(heard()).toBe("Admin · Users and roles · DEMO");
    await flush(REGION_BUDGET_MS);
    expect(heard()).toBe(NO_MFA);
  });

  it("is not held up by a clock set back while a second item waits its turn", async () => {
    await arrive();
    served = { ...NOTHING, mfa: 1, invalid: 1 };
    await flush(REREAD_MS);
    expect(heard()).toBe(NO_MFA);
    vi.setSystemTime(Date.now() - 3_600_000); // the key line is due a budget after the first
    await flush(REGION_BUDGET_MS);
    expect(heard()).toBe(KEY_REJECTED);
  });

  it("says an item again when it leaves and comes back: a new item", async () => {
    await arrive();
    served = { ...NOTHING, invalid: 1 };
    await flush(REREAD_MS);
    const first = writes();
    expect(heard()).toBe(KEY_REJECTED);
    served = NOTHING;
    await flush(REREAD_MS); // the condition ended: the strip reads "Nothing needs your action"
    expect(screen.getByRole("region", { name: "Needs your action" })).toHaveTextContent(
      "Nothing needs your action",
    );
    expect(writes()).toBe(first); // an item going says nothing
    served = { ...NOTHING, invalid: 1 };
    await flush(REREAD_MS);
    expect(writes()).not.toBe(first);
    expect(heard()).toBe(KEY_REJECTED);
  });

  it("says nothing for items a failed read dropped from the strip and a later one brought back", async () => {
    await arrive({ invalid: 1, tier: "unrecorded" });
    expect(pills()).toHaveLength(2);
    refused = { overview: 503 };
    await flush(REREAD_MS); // a failed read draws none of its items; the tier item stays
    expect(pills()).toHaveLength(1);
    refused = {};
    await flush(REREAD_MS);
    expect(pills()).toHaveLength(2);
    expect(heard()).toBeNull();
  });

  it("says nothing for an item whose slice could not be read in an answer that otherwise succeeded", async () => {
    await arrive({ mfa: 1 });
    served = { ...NOTHING, mfa: null }; // the users slice errored: no strip, nothing to compare
    await flush(REREAD_MS);
    expect(screen.queryByRole("region", { name: "Needs your action" })).toBeNull();
    served = { ...NOTHING, mfa: 1 };
    await flush(REREAD_MS);
    expect(pills()).toHaveLength(1);
    expect(heard()).toBeNull();
  });

  it("drops a line still waiting when its item left before its turn", async () => {
    await arrive();
    served = { ...NOTHING, mfa: 1, invalid: 1 };
    await flush(REREAD_MS);
    expect(heard()).toBe(NO_MFA); // the key line waits for its turn
    const last = writes();
    served = { ...NOTHING, mfa: 1 }; // the key was dealt with in the meantime
    act(() => adminReads.retry(["overview"], "test")); // a tile's Retry reads at once
    await flush();
    await flush(REGION_BUDGET_MS * 2);
    expect(writes()).toBe(last);
    expect(heard()).toBe(NO_MFA);
  });

  it("cancels a line still waiting when the area is left", async () => {
    const view = await arrive();
    served = { ...NOTHING, mfa: 1, invalid: 1 };
    await flush(REREAD_MS);
    expect(heard()).toBe(NO_MFA);
    const last = writes();
    view.rerender(<Visit show={false} />);
    await flush(REGION_BUDGET_MS * 3);
    expect(writes()).toBe(last);
    expect(heard()).toBe(NO_MFA);
  });

  it("drops a line still waiting when a 403 withdraws the area", async () => {
    await arrive();
    served = { ...NOTHING, mfa: 1, invalid: 1 };
    await flush(REREAD_MS);
    expect(heard()).toBe(NO_MFA);
    const last = writes();
    refused = { overview: 403 };
    act(() => adminReads.retry(["overview"], "test"));
    await flush();
    expect(screen.getByRole("heading", { level: 1, name: "Your access changed" })).toBeVisible();
    expect(heard("assertive")).toBe("Your access changed.");
    await flush(REGION_BUDGET_MS * 3);
    expect(writes()).toBe(last);
  });

  it("starts afresh on the next visit: the arrival is silent and an item said before is news again", async () => {
    const view = await arrive();
    served = { ...NOTHING, invalid: 1 };
    await flush(REREAD_MS);
    const first = writes();
    expect(heard()).toBe(KEY_REJECTED);
    view.rerender(<Visit show={false} />);
    await flush();
    served = NOTHING;
    view.rerender(<Visit />); // the owner comes back to nothing on the strip
    await flush();
    expect(writes()).toBe(first);
    served = { ...NOTHING, invalid: 1 };
    await flush(REREAD_MS);
    expect(writes()).not.toBe(first);
    expect(heard()).toBe(KEY_REJECTED);
  });
});
