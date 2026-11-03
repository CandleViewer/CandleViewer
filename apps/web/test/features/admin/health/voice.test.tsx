/**
 * E42-S06 (#1084) part 1b: SCR-143's voice (E42-D05 §5.3 Keys, §13): the arrival is silent; a fault
 * is said once, assertive; a recovery once, polite; a flap inside the region's 5 s budget collapses;
 * a failed report read is said once per read, polite. All through the shell's one announcer.
 */
import { act, render, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearAnnouncements, ShellAnnouncer } from "../../../../src/features/app-shell/announcer";
import { useHealthVoice, type Voiced } from "../../../../src/features/admin/health/voice";

const T = Date.parse("2026-10-22T14:02:11Z");
const region = (live: "polite" | "assertive") => document.querySelector(`[aria-live="${live}"]`);
const said = (live: "polite" | "assertive"): string => region(live)?.textContent ?? "";
const seq = (): string | null | undefined =>
  region("assertive")?.firstElementChild?.getAttribute("data-seq");
const states = (rest: string): Voiced[] => [
  { name: "bybit_rest", label: "Bybit REST", state: rest },
  { name: "oms", label: "Order manager", state: "healthy" },
];

function voice() {
  render(<ShellAnnouncer />);
  return renderHook(
    ({ s, n }: { s: Voiced[]; n?: number }) =>
      useHealthVoice(
        s,
        n === undefined ? undefined : { text: "Health report unavailable.", answers: n },
      ),
    { initialProps: { s: states("healthy") } as { s: Voiced[]; n?: number } },
  );
}
const later = (ms: number): Promise<void> =>
  act(async () => void (await vi.advanceTimersByTimeAsync(ms)));

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(T);
  clearAnnouncements();
});
afterEach(() => {
  clearAnnouncements();
  vi.useRealTimers();
});

describe("SCR-143's voice", () => {
  it("test_voice_the_arrival_is_silent_a_fault_assertive_once_and_its_recovery_polite", async () => {
    const hook = voice();
    expect([said("polite"), said("assertive")]).toEqual(["", ""]);
    hook.rerender({ s: states("down") });
    expect(said("assertive")).toBe("Health: Bybit REST down.");
    const first = seq();
    await later(6_000);
    hook.rerender({ s: states("healthy") });
    expect(said("polite")).toBe("Health: Bybit REST healthy again.");
    await later(6_000);
    hook.rerender({ s: states("down") });
    expect(said("assertive")).toBe("Health: Bybit REST down."); // a new episode, said again
    expect(seq()).not.toBe(first);
  });

  it("test_voice_a_word_not_received_ends_the_episode_so_a_return_to_down_is_said_again", async () => {
    const hook = voice();
    hook.rerender({ s: states("down") });
    const first = seq();
    await later(6_000);
    hook.rerender({ s: states("not_received") });
    expect(seq()).toBe(first); // nothing said for a word the client cannot read
    await later(6_000);
    hook.rerender({ s: states("down") });
    expect(said("assertive")).toBe("Health: Bybit REST down.");
    expect(seq()).not.toBe(first);
  });

  it("test_voice_a_flap_inside_the_regions_budget_collapses", async () => {
    const hook = voice();
    hook.rerender({ s: states("down") });
    hook.rerender({ s: states("healthy") });
    hook.rerender({ s: states("degraded") });
    expect(said("assertive")).toBe("Health: Bybit REST down.");
    hook.rerender({ s: states("down") }); // back to what was said before the budget ran out
    await later(6_000);
    expect(said("assertive")).toBe("Health: Bybit REST down.");
    expect(said("polite")).toBe("");
  });

  it("test_voice_a_failed_report_is_said_once_per_read_politely", async () => {
    const hook = voice();
    hook.rerender({ s: states("healthy"), n: 1 });
    expect(said("polite")).toBe("Health report unavailable.");
    await later(6_000);
    act(() => clearAnnouncements());
    hook.rerender({ s: states("healthy"), n: 1 });
    expect(said("polite")).toBe("");
    hook.rerender({ s: states("healthy"), n: 2 });
    expect(said("polite")).toBe("Health report unavailable.");
  });
});
