// A fake of the client the shell holds, for component tests: `useWsState` reads its `getState` and
// `subscribe`, CMP-077's `Retry now` calls its `retryNow`, the CMP-076 chip reads its `topics`. `go`
// replaces the state as a transition does; `setTopics` replaces the topics, which notify nobody (as
// frames do not): the chip reads them at its next render.
import { act } from "@testing-library/react";
import { vi } from "vitest";
import { setActiveClient } from "../../../../src/lib/ws/client/activeClient";
import type { WsClientHandle } from "../../../../src/lib/ws/client/createWsClient";
import type { TopicReading } from "../../../../src/lib/ws/state/chipState";
import { INITIAL_WS_STATE, reduce } from "../../../../src/lib/ws/state/reducer";
import type { EngineEvent, WsState } from "../../../../src/lib/ws/state/types";

export const runEvents = (...events: EngineEvent[]): WsState =>
  events.reduce(reduce, INITIAL_WS_STATE);

export function fakeActiveClient(initial: WsState = INITIAL_WS_STATE) {
  let state = initial;
  let topics: readonly TopicReading[] = [];
  const listeners = new Set<() => void>();
  const retryNow = vi.fn(() => true);
  const client = {
    getState: () => state,
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
    retryNow,
    topics: () => topics,
  } as unknown as WsClientHandle; // the shell chrome reads only these four
  const go = (next: WsState): void =>
    act(() => {
      state = next;
      listeners.forEach((listener) => listener());
    });
  const setTopics = (next: readonly TopicReading[]): void => {
    topics = next;
  };
  act(() => setActiveClient(client));
  const detach = (): void => act(() => setActiveClient(null));
  return { client, go, retryNow, detach, setTopics, current: () => state };
}
