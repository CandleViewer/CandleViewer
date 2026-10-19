// E17-T04 S5g (C11, C12; WS-E06; D5): the thin surface that CMP-076, 077, 078 and 092 read the connection through. `WsState` is
// one object that changes only when the transport, the link, the quality, the shutdown notice or the kill switch does, so a
// component re-renders on a transition and never per frame: a data message does not touch it. Without a client (the shell has
// not started, or has stopped) it is the initial state.
import { useCallback, useSyncExternalStore } from "react";
import { INITIAL_WS_STATE } from "../state/reducer";
import type { WsState } from "../state/types";
import { getActiveClient, subscribeActiveClient } from "./activeClient";

const noop = (): void => undefined;

export function useWsState(): WsState {
  const client = useSyncExternalStore(subscribeActiveClient, getActiveClient, getActiveClient);
  // a stable pair for as long as the client is the same one: React resubscribes when `subscribe` changes
  const subscribe = useCallback(
    (listener: () => void) => client?.subscribe(listener) ?? noop,
    [client],
  );
  const snapshot = useCallback((): WsState => client?.getState() ?? INITIAL_WS_STATE, [client]);
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}
