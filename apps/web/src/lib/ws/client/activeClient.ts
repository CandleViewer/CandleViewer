// E17-T04 S5g (C11, C12; WS-E06): the client the app holds. `startShell` makes one and puts it here, so a component reads the
// connection through `useWsState` and never imports the shell, and the shell stays the one thing that owns the client's life
// (a second `startShell` stops the first and takes its place).
import type { WsClient } from "../api";

let active: WsClient | null = null;
const listeners = new Set<() => void>();

export const getActiveClient = (): WsClient | null => active;

export function subscribeActiveClient(listener: () => void): () => void {
  listeners.add(listener);
  return () => void listeners.delete(listener);
}

/** `null` when the shell stops: a component then reads the initial state, as it did before the shell started. */
export function setActiveClient(client: WsClient | null): void {
  if (active === client) return;
  active = client;
  for (const listener of [...listeners]) listener();
}
