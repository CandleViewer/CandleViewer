// E17-T04 S5e (ADR-0005, D13; 23 4.1, 9.1): the shared worker's entry. One engine per origin: whichever tab connects first
// starts it, and every tab that connects after is served by the same one (`onconnect` hands each tab's port to the
// host). A browser without `SharedWorker` runs this file as a dedicated worker, which is one tab's own: the same host
// serves its one port (one socket per tab, which the gateway's 8 a user allows for a few tabs). The platform is only
// what the host cannot know: the `WebSocket` and the scope, which must be a worker's (on a page the entry throws).
// In development, and in a build made with
// `CV_ALLOW_FAULT_INJECTION=1`, the fault channel stands between the socket and the engine; in production the
// condition is `false` and the module is not in the bundle.
import type { EngineSocket, SocketFactory } from "../core/connection";
import { earlyPortOf, portOf, type MessageEndpoint } from "../port/endpoint";
import { createPortHost, type PortHost } from "./portHost";

/** The scope of a worker, typed here because the `webworker` lib cannot sit beside the DOM one. */
interface WorkerScope extends MessageEndpoint {
  /** Present on a shared worker's scope only. */
  onconnect?: ((event: { readonly ports: readonly MessageEndpoint[] }) => void) | null;
}

/** The engine's socket over the platform's: `cv.v1.json` is text, so a message that is not a string is for the codec to refuse. */
const createSocket: SocketFactory = (url, protocols, events): EngineSocket => {
  const socket = new WebSocket(url, [...protocols]);
  socket.addEventListener("open", () => events.open());
  socket.addEventListener("message", (event) => events.message(event.data));
  socket.addEventListener("close", (event) => events.close(event.code)); // an `error` is always followed by this
  return {
    send: (data) => socket.send(data),
    close: (code, reason) => socket.close(code, reason),
  };
};

async function createHost(): Promise<PortHost> {
  if (import.meta.env.DEV || __CV_ALLOW_FAULT_INJECTION__) {
    const { installFaultChannel } = await import("./faultChannel");
    const faults = installFaultChannel(createSocket);
    return createPortHost({ createSocket: faults.createSocket, fault: faults.handle });
  }
  return createPortHost({ createSocket });
}

// A page has no `WorkerGlobalScope`, and `self.onmessage` of a page is every message posted to it: the entry takes no port there.
const WorkerType = (globalThis as { WorkerGlobalScope?: abstract new () => object })
  .WorkerGlobalScope;
if (WorkerType === undefined || !(self instanceof WorkerType)) {
  throw new Error("wsWorker.ts is the entry of a worker: it takes no port on a page");
}

const scope = self as unknown as WorkerScope;
const host = createHost();
let failures = 0;
/** A host that did not start, or a tab that was not served: a count, never the error, which may name a URL. */
const failed = (): void => {
  failures += 1;
  console.error(`wsWorker: ${failures} tab(s) not served`);
};
if (scope.onconnect !== undefined) {
  // Registered now, before the host exists: a tab that connects while it is being made is served in turn.
  scope.onconnect = (event) => {
    for (const port of event.ports) {
      void host.then((ready) => ready.attach(portOf(port))).catch(failed);
    }
  };
} else {
  // A dedicated worker's own scope delivers from the moment this script has run, so its handler is set now: what the tab says
  // before the host is ready (in development, before the channel's chunk is loaded) is kept and served in order.
  const port = earlyPortOf(scope);
  void host
    .then((ready) => {
      ready.attach(port);
      if (port.refused > 0)
        console.error(`wsWorker: ${port.refused} message(s) refused before the host was ready`);
    })
    .catch(failed);
}
