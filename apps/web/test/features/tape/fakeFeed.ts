// E22-S01 (#714): a fake WS client and display for the tape's feed loop.
import { vi, type Mock } from "vitest";
import type {
  ConsumerSpec,
  PaneVisibility,
  TopicFrame,
  TopicHandle,
} from "../../../src/lib/ws/api";
import type { TopicStatus } from "../../../src/lib/ws/state/types";
import type { TapeClock } from "../../../src/features/tape/model/tapeFeed";

export interface FakeHandle extends TopicHandle {
  queue: TopicFrame[];
  status: TopicStatus;
}

export interface FakeClient {
  readonly client: {
    readonly consume: Mock<(spec: ConsumerSpec) => TopicHandle>;
    readonly setPane: Mock<(paneId: string, visibility: PaneVisibility) => void>;
  };
  readonly handles: FakeHandle[];
  readonly specs: ConsumerSpec[];
}

export function fakeClient(): FakeClient {
  const handles: FakeHandle[] = [];
  const specs: ConsumerSpec[] = [];
  const client = {
    consume: vi.fn((spec: ConsumerSpec): TopicHandle => {
      specs.push(spec);
      const handle: FakeHandle = {
        ch: spec.ch,
        queue: [],
        status: "pending",
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
    setPane: vi.fn<(paneId: string, visibility: PaneVisibility) => void>(),
  };
  return { client, handles, specs };
}

/** A manual display and monotonic clock: `frame()` runs what was requested. */
export function fakeDisplay(stepMs = 20) {
  const requested = new Map<number, (t: number) => void>();
  let handle = 0;
  let nowMs = 0;
  const clock: TapeClock = {
    raf: (callback) => {
      handle += 1;
      requested.set(handle, callback);
      return handle;
    },
    caf: (id) => void requested.delete(id),
    now: () => nowMs,
  };
  return {
    clock,
    pending: () => requested.size,
    frame: () => {
      nowMs += stepMs;
      const callbacks = [...requested.values()];
      requested.clear();
      for (const callback of callbacks) callback(nowMs);
    },
  };
}
