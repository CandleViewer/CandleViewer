/**
 * The ticker client's transport over the WS client's public API (E17-T04, `lib/ws/api.ts`): one `consume` of the batched
 * `ticker` with its `symbols` (`23` §6.1), read on the hub's beat, released to let go. Nothing here reaches into the
 * client's internals. One hub per WS client: the app's connection (a shared worker's) carries one batched `ticker`.
 */
import { useSyncExternalStore } from "react";
import type { WsClient } from "../../../lib/ws/api";
import { getActiveClient, subscribeActiveClient } from "../../../lib/ws/client/activeClient";
import { createTickerHub, type TickerHub, type TickerTransport } from "./tickerHub";

export const TICKER_CHANNEL = "ticker";
/** The WS client's pane for the batched `ticker`: one subscription serves every watchlist pane. */
export const TICKER_PANE = "watchlist";

export function wsTickerTransport(client: WsClient): TickerTransport {
  return {
    open([first, ...rest]) {
      const handle = client.consume({
        ch: TICKER_CHANNEL,
        opts: { symbols: [first, ...rest] },
        paneId: TICKER_PANE,
        priority: "other",
      });
      return {
        read: () => handle.read(),
        get status() {
          return handle.status;
        },
        release: () => handle.release(),
      };
    },
  };
}

const hubs = new Map<WsClient, TickerHub>();
let watching = false;

/** A client the shell no longer holds takes its hub with it (its subscription went with the client). */
function watchClients(): void {
  if (watching) return;
  watching = true;
  subscribeActiveClient(() => {
    const active = getActiveClient();
    for (const [client, hub] of hubs) {
      if (client === active) continue;
      hub.dispose();
      hubs.delete(client);
    }
  });
}

/** The hub of `client`, made once and held while the client is the app's. Making one subscribes nothing. */
export function hubFor(client: WsClient): TickerHub {
  watchClients();
  const held = hubs.get(client);
  if (held !== undefined) return held;
  const hub = createTickerHub(wsTickerTransport(client));
  hubs.set(client, hub);
  return hub;
}

/** The hub of the app's WS client, or `null` while the shell holds none. */
export function useTickerHub(): TickerHub | null {
  const client = useSyncExternalStore(subscribeActiveClient, getActiveClient, getActiveClient);
  return client === null ? null : hubFor(client);
}
