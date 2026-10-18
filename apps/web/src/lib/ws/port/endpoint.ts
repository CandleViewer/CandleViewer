// E17-T04 S5e (ADR-0005): what a port is, on either side of it. A `MessagePort` (a shared worker's tab), a `Worker` (the
// tab's end of a dedicated one) and a dedicated worker's own scope all post a message with the buffers to transfer and
// take an `onmessage`; the host and the client want only that, and `PortLike` is the smallest form of it, so a test can
// put a fake or a `MessageChannel` where the browser puts the real thing.
export interface PortLike {
  /** `transfer` buffers are detached at the sender and reach the other end without a copy. */
  postMessage(message: unknown, transfer: ArrayBuffer[]): void;
  /** Starts delivery of the port's messages: `handler` gets each message's data. */
  listen(handler: (data: unknown) => void): void;
}

/** What `MessagePort`, `Worker` and a dedicated worker's scope have in common. Assigning `onmessage` starts a `MessagePort`. */
export interface MessageEndpoint {
  postMessage(message: unknown, transfer: Transferable[]): void;
  onmessage: ((event: MessageEvent) => unknown) | null;
}

export function portOf(endpoint: MessageEndpoint): PortLike {
  return {
    postMessage: (message, transfer) => endpoint.postMessage(message, transfer),
    listen: (handler) => {
      endpoint.onmessage = (event) => handler(event.data);
    },
  };
}

/** How many messages the port of `earlyPortOf` keeps for a listener that is not there yet. */
export const MAX_EARLY_MESSAGES = 128;

/**
 * The port of an endpoint that starts delivering the moment the script has run, as a dedicated worker's own scope does: a
 * handler set later finds nothing of what came before it. The handler is set now; what arrives before `listen` is kept, in
 * order, up to `MAX_EARLY_MESSAGES`, and handed to the listener when it comes; what is past the bound is counted, not kept.
 */
export function earlyPortOf(endpoint: MessageEndpoint): PortLike & { readonly refused: number } {
  const early: unknown[] = [];
  let refused = 0;
  let handler: ((data: unknown) => void) | undefined;
  endpoint.onmessage = (event) => {
    if (handler !== undefined) handler(event.data);
    else if (early.length < MAX_EARLY_MESSAGES) early.push(event.data);
    else refused += 1;
  };
  return {
    postMessage: (message, transfer) => endpoint.postMessage(message, transfer),
    listen: (next) => {
      handler = next;
      for (const data of early.splice(0)) next(data);
    },
    get refused() {
      return refused;
    },
  };
}
