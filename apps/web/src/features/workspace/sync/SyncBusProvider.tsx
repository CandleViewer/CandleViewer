/**
 * Puts one workspace's SyncBus in context for CMP-196's hook. The caller creates the bus (one per
 * workspace) so its lifetime is the workspace's; this component renders nothing of its own.
 */
import { createContext, useContext, type JSX, type ReactNode } from "react";
import { REGION_BUDGET_MS, announce, forget, lastWrittenAt } from "../../app-shell/announcer";
import type { SyncBus } from "./syncBus";

const SyncBusContext = createContext<SyncBus | null>(null);

export function SyncBusProvider(props: { bus: SyncBus; children?: ReactNode }): JSX.Element {
  return <SyncBusContext.Provider value={props.bus}>{props.children}</SyncBusContext.Provider>;
}

/** The workspace's bus, or null outside a provider (the hook then does nothing). */
export function useSyncBus(): SyncBus | null {
  return useContext(SyncBusContext);
}

const ANNOUNCE_KEY = "sync:linked";

/**
 * CMP-196's writer for `createSyncBus({ announce })`: the shell's one polite region, within its
 * budget (REGION_BUDGET_MS since its last write). Text arriving while it waits joins the queued
 * message, so nothing is dropped; the key is forgotten first so a later change is said again.
 * Each announcer owns its queue and timer, so a test gets a fresh one.
 */
export function createSyncAnnouncer(): (text: string) => void {
  const pending: string[] = [];
  let timer: ReturnType<typeof setTimeout> | undefined;
  function write(): void {
    const wait = lastWrittenAt("polite") + REGION_BUDGET_MS - Date.now();
    if (wait > 0) {
      timer = setTimeout(write, wait);
      return;
    }
    timer = undefined;
    forget(ANNOUNCE_KEY);
    announce("polite", pending.splice(0).join(" "), ANNOUNCE_KEY);
  }
  return (text) => {
    pending.push(text);
    if (timer === undefined) write();
  };
}

/** The app's announcer: one instance, as the shell has one polite region. */
export const announceSyncState = createSyncAnnouncer();
