/**
 * E42-S08 (#1137) §3.4: the open machine's live state (BQ-7 as recommended, not yet ruled). One
 * `machines.{key}.state` subscription with no option, for the open machine only and only in the
 * shell's environment; frames drained once per animation frame, never per arrival; each body vetted
 * as `MachinesEntityState`; the page told only of a change of state, regions or latch; the latch
 * seen live said once, assertively; a refused subscription silent; released on a machine change
 * and on unmount (the teardown, `.claude/rules/30-frontend-react.md`). The client derives nothing.
 */
import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ConsumerSpec, TopicFrame, TopicHandle } from "../../../../src/lib/ws/api";
import { setActiveClient } from "../../../../src/lib/ws/client/activeClient";
import type { WsClientHandle } from "../../../../src/lib/ws/client/createWsClient";
import { clearAnnouncements, ShellAnnouncer } from "../../../../src/features/app-shell/announcer";
import type { MachineRef } from "../../../../src/features/admin/statecharts/inspectorReads";
import {
  FEED_PANE,
  startMachineFeed,
  useMachineFeed,
  vetMachineState,
  type FeedClock,
  type LiveState,
  type SavedState,
} from "../../../../src/features/admin/statecharts/machineFeed";
import { resetShellState, setShellState } from "../../../../src/shell/bootstrap/store";
import { LATCHED_KEY, ORDER_HASH } from "./fixtures";

const LATCHED: MachineRef = { key: LATCHED_KEY, env: "demo" };
const OTHER: MachineRef = { key: "order:0a000000-0000-4000-8000-000000000001", env: "demo" };
const AT = Date.parse("2026-10-15T18:00:09Z");

/** A `MachinesEntityState` of the latched order (`23` §15.10), with `patch`. */
const payload = (patch: Readonly<Record<string, unknown>> = {}) => ({
  machine_kind: "order",
  state: "triggered",
  regions: { lifecycle: "triggered", protection: "sl_present" },
  tags: ["protected"],
  degraded: true,
  machine_hash: ORDER_HASH,
  environment: "demo",
  updated_at_ms: AT,
  ...patch,
});
const stamp = { seq: 1, ts: AT, sp: undefined, decodeMs: 0, size: 0, meta: undefined } as const;
const snap = (p: unknown): TopicFrame => ({ ...stamp, kind: "snap", bodies: [{ e: "j", p }] });
const delta = (p: unknown): TopicFrame => ({ ...stamp, kind: "d", body: { e: "j", p } });

interface FakeHandle extends TopicHandle {
  queue: TopicFrame[];
}

/** A WS client whose handles the test fills, and a display whose frames the test runs. */
function fakes() {
  const handles: FakeHandle[] = [];
  const specs: ConsumerSpec[] = [];
  const client = {
    consume: vi.fn((spec: ConsumerSpec): TopicHandle => {
      specs.push(spec);
      const handle: FakeHandle = {
        ch: spec.ch,
        queue: [],
        status: "live",
        effective: {},
        source: "live",
        rs: undefined,
        read() {
          const drained = handle.queue;
          handle.queue = [];
          return drained;
        },
        release: vi.fn(),
      };
      handles.push(handle);
      return handle;
    }),
  };
  const requested = new Map<number, (t: number) => void>();
  let next = 0;
  const clock: FeedClock = {
    raf: (callback) => {
      next += 1;
      requested.set(next, callback);
      return next;
    },
    caf: (handle) => void requested.delete(handle),
  };
  /** Runs the animation frame the loop asked for. */
  const frame = (): void => {
    const due = [...requested.values()];
    requested.clear();
    for (const callback of due) callback(0);
  };
  return { client, handles, specs, clock, frame, pending: () => requested.size };
}

describe("startMachineFeed: one topic, read per animation frame", () => {
  it("test_feed_subscribes_to_the_machines_topic_with_no_option", () => {
    const { client, specs, clock } = fakes();
    const stop = startMachineFeed(client, LATCHED, () => undefined, clock);
    expect(specs).toEqual([
      { ch: `machines.${LATCHED_KEY}.state`, paneId: FEED_PANE, priority: "other" },
    ]);
    expect(FEED_PANE).toBe("admin-statecharts");
    stop();
  });

  it("test_feed_reads_frames_per_animation_frame_never_per_arrival", () => {
    const { client, handles, clock, frame } = fakes();
    const heard: (LiveState | null)[] = [];
    const stop = startMachineFeed(client, LATCHED, (live) => heard.push(live), clock);
    const handle = handles[0] as FakeHandle;
    handle.queue.push(snap(payload({ state: "submitted" })), delta(payload()));
    expect(heard).toEqual([]); // nothing on arrival
    frame();
    expect(heard).toEqual([
      {
        state: "triggered",
        regions: { lifecycle: "triggered", protection: "sl_present" },
        degraded: true,
        at: AT,
      },
    ]); // the latest of the batch, once
    stop();
  });

  it("test_feed_tells_only_a_change_of_state_regions_or_latch", () => {
    const { client, handles, clock, frame } = fakes();
    const heard: (LiveState | null)[] = [];
    const stop = startMachineFeed(client, LATCHED, (live) => heard.push(live), clock);
    const handle = handles[0] as FakeHandle;
    handle.queue.push(snap(payload()));
    frame();
    handle.queue.push(delta(payload({ updated_at_ms: AT + 1_000 })));
    frame();
    frame(); // an empty frame says nothing
    expect(heard).toHaveLength(1);
    handle.queue.push(
      delta(payload({ regions: { lifecycle: "triggered", protection: "sl_pending" } })),
    );
    frame();
    handle.queue.push(delta(payload({ state: "filled", regions: undefined })));
    frame();
    handle.queue.push(delta(payload({ state: "filled", regions: undefined, degraded: false })));
    frame();
    expect(heard.map((live) => [live?.state, live?.degraded])).toEqual([
      ["triggered", true],
      ["triggered", true],
      ["filled", true],
      ["filled", false],
    ]);
    stop();
  });

  it.each([
    ["an unknown kind", { machine_kind: "position_protection" }],
    ["an empty state", { state: "" }],
    ["a state over 200 characters", { state: "s".repeat(201) }],
    ["thirty-three tags", { tags: Array.from({ length: 33 }, (_, i) => `t${i}`) }],
    ["a latch that is no boolean", { degraded: "true" }],
    ["a hash off its pattern", { machine_hash: "A".repeat(64) }],
    ["another environment's body", { environment: "live" }],
    ["a time that is no integer", { updated_at_ms: 1.5 }],
    ["an empty region name", { regions: { "": "triggered" } }],
    ["a region's state over 200 characters", { regions: { lifecycle: "s".repeat(201) } }],
    ["a region's state that is no string", { regions: { lifecycle: 1 } }],
  ])("test_feed_drops_%s", (_name, patch) => {
    const { client, handles, clock, frame } = fakes();
    const heard: (LiveState | null)[] = [];
    const stop = startMachineFeed(client, LATCHED, (live) => heard.push(live), clock);
    (handles[0] as FakeHandle).queue.push(snap(payload(patch)));
    frame();
    expect(heard).toEqual([]);
    expect(vetMachineState(payload(patch), LATCHED)).toBeNull();
    stop();
  });

  it("test_feed_reads_any_state_and_region_name_up_to_200_characters", () => {
    // Shown only, never a path: `22` and the chart schema constrain these names no further.
    const long = "s".repeat(200);
    const live = vetMachineState(
      payload({ state: "wait-fill", regions: { "life-cycle": long, protection: "sl present" } }),
      LATCHED,
    );
    expect(live).toEqual({
      state: "wait-fill",
      regions: { "life-cycle": long, protection: "sl present" },
      degraded: true,
      at: AT,
    });
  });

  it("test_feed_drops_a_binary_body", () => {
    const { client, handles, clock, frame } = fakes();
    const heard: (LiveState | null)[] = [];
    const stop = startMachineFeed(client, LATCHED, (live) => heard.push(live), clock);
    const binary: TopicFrame = {
      ...stamp,
      kind: "d",
      body: { e: "b64", bytes: new ArrayBuffer(8) },
    };
    (handles[0] as FakeHandle).queue.push(binary);
    frame();
    expect(heard).toEqual([]);
    stop();
  });

  it("test_feed_a_reset_voids_what_was_shown", () => {
    const { client, handles, clock, frame } = fakes();
    const heard: (LiveState | null)[] = [];
    const stop = startMachineFeed(client, LATCHED, (live) => heard.push(live), clock);
    const handle = handles[0] as FakeHandle;
    handle.queue.push(snap(payload()));
    frame();
    handle.queue.push({ kind: "reset", reason: "revoked" });
    frame();
    expect(heard.at(-1)).toBeNull();
    stop();
  });

  it("test_feed_stop_releases_and_ends_the_loop_once", () => {
    const { client, handles, clock, pending } = fakes();
    const stop = startMachineFeed(client, LATCHED, () => undefined, clock);
    expect(pending()).toBe(1);
    stop();
    stop();
    expect(pending()).toBe(0);
    expect((handles[0] as FakeHandle).release).toHaveBeenCalledTimes(1);
  });
});

/** The hook in a component, as the machine view holds it. */
function Probe({
  machine,
  saved,
  clock,
  onLive,
}: {
  readonly machine: MachineRef;
  readonly saved: SavedState | undefined;
  readonly clock: FeedClock;
  readonly onLive: (live: LiveState | null) => void;
}): null {
  onLive(useMachineFeed(machine, saved, clock));
  return null;
}

const assertive = (): HTMLElement | null =>
  document.querySelector<HTMLElement>('[aria-live="assertive"] p');

describe("useMachineFeed: the open machine, in the shell's environment", () => {
  beforeEach(() => {
    clearAnnouncements();
    setShellState({ environment: "demo" });
  });
  afterEach(() => {
    act(() => setActiveClient(null));
    clearAnnouncements();
    resetShellState();
  });

  function mount(machine: MachineRef, saved: SavedState | undefined = undefined) {
    const f = fakes();
    act(() => setActiveClient(f.client as unknown as WsClientHandle));
    const seen: (LiveState | null)[] = [];
    const view = render(
      <>
        <Probe machine={machine} saved={saved} clock={f.clock} onLive={(l) => seen.push(l)} />
        <ShellAnnouncer />
      </>,
    );
    const rerender = (next: MachineRef, nextSaved: SavedState | undefined = saved): void =>
      view.rerender(
        <>
          <Probe machine={next} saved={nextSaved} clock={f.clock} onLive={(l) => seen.push(l)} />
          <ShellAnnouncer />
        </>,
      );
    return { ...f, view, seen, rerender };
  }

  it("test_feed_hook_subscribes_only_in_the_shells_environment", () => {
    setShellState({ environment: "live" });
    const { specs } = mount(LATCHED);
    expect(specs).toEqual([]);
    act(() => setShellState({ environment: "demo" }));
    expect(specs.map((s) => s.ch)).toEqual([`machines.${LATCHED_KEY}.state`]);
  });

  it("test_feed_hook_without_a_client_subscribes_to_nothing", () => {
    const seen: (LiveState | null)[] = [];
    render(
      <Probe
        machine={LATCHED}
        saved={undefined}
        clock={fakes().clock}
        onLive={(l) => seen.push(l)}
      />,
    );
    expect(seen.every((live) => live === null)).toBe(true);
  });

  it("test_feed_hook_releases_on_a_machine_change_and_on_unmount", () => {
    const { handles, view, rerender, specs } = mount(LATCHED);
    rerender(OTHER);
    expect((handles[0] as FakeHandle).release).toHaveBeenCalledTimes(1);
    expect(specs.map((s) => s.ch)).toEqual([
      `machines.${LATCHED_KEY}.state`,
      `machines.${OTHER.key}.state`,
    ]);
    view.unmount();
    expect((handles[1] as FakeHandle).release).toHaveBeenCalledTimes(1);
  });

  it("test_feed_hook_says_the_latch_seen_live_once_assertively", () => {
    const { handles, frame, seen } = mount(LATCHED, { state: "triggered", degraded: false });
    act(() => {
      (handles[0] as FakeHandle).queue.push(snap(payload()));
      frame();
    });
    expect(seen.at(-1)?.degraded).toBe(true);
    expect(assertive()).toHaveTextContent(`${LATCHED_KEY} latched.`);
    const said = assertive()?.dataset["seq"];
    act(() => {
      (handles[0] as FakeHandle).queue.push(delta(payload({ state: "filled" })));
      frame();
    });
    expect(assertive()?.dataset["seq"]).toBe(said); // one episode, one line
  });

  it("test_feed_hook_a_machine_opened_again_says_its_latch_again", () => {
    // The episode ends with the view: the machine closed and opened again is a new episode.
    const first = mount(LATCHED, { state: "triggered", degraded: false });
    act(() => {
      (first.handles[0] as FakeHandle).queue.push(snap(payload()));
      first.frame();
    });
    expect(assertive()).toHaveTextContent(`${LATCHED_KEY} latched.`);
    const said = assertive()?.dataset["seq"];
    first.view.unmount();
    const again = mount(LATCHED, { state: "triggered", degraded: false });
    act(() => {
      (again.handles[0] as FakeHandle).queue.push(snap(payload()));
      again.frame();
    });
    expect(assertive()).toHaveTextContent(`${LATCHED_KEY} latched.`);
    expect(assertive()?.dataset["seq"]).not.toBe(said);
  });

  it("test_feed_hook_says_nothing_when_the_saved_snapshot_is_latched_already", () => {
    const { handles, frame } = mount(LATCHED, { state: "triggered", degraded: true });
    act(() => {
      (handles[0] as FakeHandle).queue.push(snap(payload()));
      frame();
    });
    expect(assertive()).toBeNull();
  });

  it("test_feed_hook_a_refused_subscription_shows_and_says_nothing", () => {
    const { handles, frame, seen } = mount(LATCHED, { state: "triggered", degraded: false });
    act(() => {
      (handles[0] as FakeHandle).queue.push({ kind: "reset", reason: "revoked" });
      frame();
    });
    expect(seen.every((live) => live === null)).toBe(true);
    expect(assertive()).toBeNull();
    expect(document.querySelector('[aria-live="polite"] p')).toBeNull();
  });
});
