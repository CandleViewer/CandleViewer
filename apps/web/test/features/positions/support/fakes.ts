/**
 * Test support for the positions feature (E29-S01 #911): the goldens the shipped Python mappers
 * write (`packages/fixtures/golden/positions/`, BQ-22), and a fake WS client whose topic handles
 * hold the frames a test pushes until `read()` drains them, as the real client's queue does.
 */
import { INITIAL_WS_STATE } from "../../../../src/lib/ws/state/reducer";
import type {
  ConsumerSpec,
  ResetReason,
  TopicFrame,
  TopicHandle,
  WsClient,
} from "../../../../src/lib/ws/api";
import type { Link, TopicStatus, WsState } from "../../../../src/lib/ws/state/types";
import { repoFile } from "../../../lib/ws/support/schemaHarness";

export const GOLDEN_DIR = "packages/fixtures/golden/positions";
export const golden = <T = unknown>(name: string): T =>
  JSON.parse(repoFile(`${GOLDEN_DIR}/${name}`)) as T;

/** The three fixture accounts (the manifest's remapping, D02 §5.2's labels). */
export const MAIN = "a1000000-0000-4000-8000-000000000001";
export const SUB1 = "a1000000-0000-4000-8000-000000000002";
export const SUB2 = "a1000000-0000-4000-8000-000000000003";
export const GROUP = "0c000000-0000-4000-8000-000000000001";

let seq = 0;
const stamped = (ts: number) => ({ seq: (seq += 1), ts, sp: undefined, decodeMs: 0, size: 0 });

export const snap = (p: unknown, ts = 1_793_455_331_100): TopicFrame => ({
  kind: "snap",
  ...stamped(ts),
  meta: undefined,
  bodies: [{ e: "j", p }],
});
export const delta = (p: unknown, ts = 1_793_455_332_100): TopicFrame => ({
  kind: "d",
  ...stamped(ts),
  meta: undefined,
  body: { e: "j", p },
});
export const reset = (reason: ResetReason): TopicFrame => ({ kind: "reset", reason });

export interface FakeHandle extends TopicHandle {
  readonly spec: ConsumerSpec;
  push(...frames: TopicFrame[]): void;
  setEffective(effective: Readonly<Record<string, unknown>>): void;
  setStatus(status: TopicStatus): void;
  readonly released: boolean;
}

export interface FakeClient {
  readonly client: Pick<WsClient, "consume" | "getState" | "subscribe">;
  readonly handles: FakeHandle[];
  /** The live (not released) handles of `ch`. */
  live(ch: string): FakeHandle[];
  setLink(link: Link): void;
  setState(patch: Partial<WsState>): void;
}

export function fakeClient(): FakeClient {
  const handles: FakeHandle[] = [];
  const listeners = new Set<() => void>();
  let state: WsState = { ...INITIAL_WS_STATE, link: { kind: "up" }, transport: "connected" };
  const client: FakeClient["client"] = {
    consume(spec) {
      let queue: TopicFrame[] = [];
      let effective: Readonly<Record<string, unknown>> = {};
      let status: TopicStatus = "pending";
      let released = false;
      const handle: FakeHandle = {
        spec,
        ch: spec.ch,
        rs: undefined,
        source: "live",
        read: () => {
          const out = queue;
          queue = [];
          return out;
        },
        get effective() {
          return effective;
        },
        get status() {
          return status;
        },
        get released() {
          return released;
        },
        release: () => {
          released = true;
        },
        push: (...frames) => {
          queue.push(...frames);
        },
        setEffective: (next) => {
          effective = next;
        },
        setStatus: (next) => {
          status = next;
        },
      };
      handles.push(handle);
      return handle;
    },
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
  };
  return {
    client,
    handles,
    live: (ch) => handles.filter((h) => h.ch === ch && !h.released),
    setLink(link) {
      state = { ...state, link };
      listeners.forEach((l) => l());
    },
    setState(patch) {
      state = { ...state, ...patch };
      listeners.forEach((l) => l());
    },
  };
}

/** `requestAnimationFrame` on the fake clock: one frame is 16 ms. */
export const fakeRaf = {
  raf: (callback: (t: number) => void): number =>
    setTimeout(() => callback(Date.now()), 16) as unknown as number,
  caf: (handle: number): void => clearTimeout(handle),
};
