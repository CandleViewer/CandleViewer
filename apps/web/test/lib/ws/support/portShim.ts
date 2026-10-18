// A worker's host over the fake gateway and tabs that reach it through real message channels: a transferred buffer is
// detached at the sender and structured-cloned at the receiver. Timers are real (a message port delivers on the event loop).
import { onTestFinished } from "vitest";
import { createWsClient } from "../../../../src/lib/ws/client/createWsClient";
import { portOf, type PortLike } from "../../../../src/lib/ws/port/endpoint";
import type { WorkerMessage } from "../../../../src/lib/ws/port/messages";
import { createPortHost } from "../../../../src/lib/ws/worker/portHost";
import { tokenOf, URL } from "./connectionHarness";
import { createFakeGateway } from "./fakeGateway";
import { fakePage } from "./fakePage";

/** How long a test waits for the event loop to carry a message through a port and the engine. */
export const WAIT = { timeout: 5_000, interval: 10 };

/** The worker's host over the fake gateway, and tabs that reach it through message channels. */
export function shim() {
  const gateway = createFakeGateway();
  const host = createPortHost({ createSocket: gateway.createSocket, random: () => 0.5 });
  /** What the host posted to a tab, and the size of each buffer it transferred, as it was once the post returned. */
  const posted: { tab: number; message: WorkerMessage; detached: number[] }[] = [];
  let tabs = 0;
  onTestFinished(() => host.dispose());

  /** A tab's end of a port that the host serves. */
  function attach(): { port: PortLike; index: number; close(): void } {
    const index = (tabs += 1);
    const channel = new MessageChannel();
    const hostEnd = portOf(channel.port1);
    host.attach({
      listen: hostEnd.listen,
      postMessage(message, transfer) {
        hostEnd.postMessage(message, transfer);
        posted.push({
          tab: index,
          message: message as WorkerMessage,
          detached: transfer.map((b) => b.byteLength),
        });
      },
    });
    return {
      port: portOf(channel.port2),
      index,
      close: () => {
        channel.port1.close();
        channel.port2.close();
      },
    };
  }

  function tab() {
    const { port, close } = attach();
    const page = fakePage();
    let issued = 0;
    const client = createWsClient({
      wsUrl: URL,
      tokens: {
        getToken: async () => ({
          kind: "ok",
          accessToken: tokenOf((issued += 1)),
          expiresAtMs: Date.now() + 600_000,
        }),
        invalidate: () => undefined,
      },
      shell: "browser",
      locale: "en-GB",
      clientVersion: "1.0.0",
      port,
      page: page.page,
    });
    onTestFinished(() => {
      client.stop();
      close();
    });
    return { client, page };
  }
  return { gateway, tab, attach, posted };
}
