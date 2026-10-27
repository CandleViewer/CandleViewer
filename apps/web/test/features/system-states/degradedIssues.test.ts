// E10-S04 (#306) SCR-153: the degraded-issue derivation from `SystemUpdate` payloads (ticket Test
// plan, first unit item). The copy is E17-D02 §8's, verbatim; the routing is its §6 table.
import { describe, expect, it } from "vitest";
import type { SystemUpdate } from "../../../src/lib/ws/protocol/frames";
import { DEGRADED_COPY } from "../../../src/features/system-states/copy";
import {
  INITIAL_DEGRADED_FACTS,
  degradedIssues,
  reduceDegraded,
  type DegradedFacts,
} from "../../../src/features/system-states/degradedIssues";

const run = (...updates: unknown[]): DegradedFacts =>
  updates.reduce<DegradedFacts>(
    (facts, u) => reduceDegraded(facts, u as SystemUpdate),
    INITIAL_DEGRADED_FACTS,
  );
const ids = (facts: DegradedFacts): string[] => degradedIssues(facts).map((i) => i.id);

const health = (components: unknown[], extra: object = {}): SystemUpdate =>
  ({ kind: "health", health: "degraded", components, ...extra }) as SystemUpdate;
const exchangeState = (p: object): SystemUpdate =>
  ({ kind: "exchange_state", ...p }) as SystemUpdate;

describe("degraded issues", () => {
  it("test_degraded_exchange_ws_down_names_the_feed_and_what_still_works", () => {
    const [issue] = degradedIssues(run(exchangeState({ public_ws: "disconnected" })));
    expect(issue).toEqual({
      id: "exchangeFeedDown",
      severity: "warning",
      message: "Exchange feed down — the server is restoring the connection.",
      stillWorks: "Charts and book pause; positions, cancel and close still work.",
      dismissible: true,
      assertedSeq: 1,
    });
    // ticket AC "honest about scope": never implies the whole app is broken
    expect(`${issue?.message} ${issue?.stillWorks}`).not.toMatch(/trading is off|new orders off/i);
  });

  it.each(["connecting", "disconnected"])("test_degraded_public_ws_%s_is_down", (v) => {
    expect(ids(run(exchangeState({ exchange: { public_ws: v } })))).toEqual(["exchangeFeedDown"]);
  });

  it("test_degraded_public_feed_clears_on_connected_or_resyncing", () => {
    const down = exchangeState({ public_ws: "connecting" });
    expect(ids(run(down, exchangeState({ public_ws: "connected" })))).toEqual([]);
    expect(ids(run(down, exchangeState({ public_ws: "resyncing" })))).toEqual([]);
    // the topic snapshot's `health.exchange` carries the same fact
    expect(ids(run(down, health([], { exchange: { public_ws: "connected" } })))).toEqual([]);
  });

  it("test_degraded_top_level_public_ws_wins_over_the_nested_one", () => {
    const u = exchangeState({ public_ws: "disconnected", exchange: { public_ws: "connected" } });
    expect(ids(run(u))).toEqual(["exchangeFeedDown"]);
  });

  it("test_degraded_component_down_maps_to_its_row_and_clears_when_not_down", () => {
    const down = health([
      { name: "rule_engine", state: "down" },
      { name: "recorder", state: "down" },
    ]);
    const facts = run(down);
    expect(degradedIssues(facts).map((i) => [i.id, i.severity])).toEqual([
      ["ruleEngineDown", "info"],
      ["recorderDown", "info"],
    ]);
    expect(ids(run(down, health([{ name: "recorder", state: "degraded" }])))).toEqual([
      "ruleEngineDown",
    ]);
  });

  it("test_degraded_store_down_and_maintenance_are_blocking_rows_first", () => {
    const facts = run(
      health([{ name: "recorder", state: "down" }]),
      exchangeState({ public_ws: "disconnected" }),
      health([{ name: "postgres", state: "down" }]),
      { kind: "notice", severity: "warning", reason: "maintenance.enabled", message: "x" },
    );
    expect(degradedIssues(facts).map((i) => [i.id, i.severity])).toEqual([
      ["maintenance", "blocking"],
      ["storeDown", "blocking"],
      ["exchangeFeedDown", "warning"],
      ["recorderDown", "info"],
    ]);
    expect(degradedIssues(facts)[1]?.stillWorks).toBeNull();
  });

  it("test_degraded_maintenance_disabled_clears_and_other_notices_change_nothing", () => {
    const on = { kind: "notice", reason: "maintenance.enabled" };
    const facts = run(on, { kind: "notice", reason: "auth.break_glass_used" });
    expect(ids(facts)).toEqual(["maintenance"]);
    expect(ids(run(on, { kind: "notice", reason: "maintenance.disabled" }))).toEqual([]);
  });

  it("test_degraded_overall_health_word_and_other_components_route_nothing", () => {
    const facts = run(
      health([
        { name: "questdb", state: "down" },
        { name: "postgres", state: "degraded" },
      ]),
    );
    expect(facts).toBe(INITIAL_DEGRADED_FACTS);
    expect(degradedIssues(facts)).toEqual([]);
  });

  it("test_degraded_each_reassertion_bumps_assertedSeq_so_a_dismissal_reappears", () => {
    const down = exchangeState({ public_ws: "disconnected" });
    expect(degradedIssues(run(down, down, down))[0]?.assertedSeq).toBe(3);
    // a new episode starts the count again
    const up = exchangeState({ public_ws: "connected" });
    expect(degradedIssues(run(down, down, up, down))[0]?.assertedSeq).toBe(1);
  });

  it("test_degraded_untrusted_or_unrelated_frames_keep_the_same_facts", () => {
    const facts = run(health([{ name: "recorder", state: "down" }]));
    for (const junk of [
      null,
      [],
      "health",
      { kind: "health", components: "x" },
      { kind: "health", components: [null, { name: "__proto__", state: "down" }] },
      { kind: "exchange_state", public_ws: "sideways" },
      { kind: "kill_switch", exchange: { public_ws: "disconnected" } },
      { kind: "connection_quality", class: "lagging" },
    ]) {
      expect(reduceDegraded(facts, junk as unknown as SystemUpdate)).toBe(facts);
    }
  });

  it("test_degraded_facts_are_frozen_and_never_mutated", () => {
    const first = run(exchangeState({ public_ws: "disconnected" }));
    const second = reduceDegraded(first, exchangeState({ public_ws: "connected" }));
    expect(Object.isFrozen(second)).toBe(true);
    expect(ids(first)).toEqual(["exchangeFeedDown"]);
    expect(ids(second)).toEqual([]);
  });

  it("test_degraded_copy_rows_have_a_message_and_full_stops", () => {
    for (const row of Object.values(DEGRADED_COPY)) {
      expect(row.message).toMatch(/\.$/);
      if (row.stillWorks !== null) expect(row.stillWorks).toMatch(/\.$/);
    }
  });
});
