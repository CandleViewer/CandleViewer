// Shared setup of the host tests: a tab's end of a port (it records what the worker posts, with the transfer
// list, and answers the worker's token requests on its own), and a host over the fake gateway.
import { onTestFinished, vi } from "vitest";
import type { WorkerMessage } from "../../../../src/lib/ws/port/messages";
import {
  createPortHost,
  type PortHostOptions,
  type PortLike,
} from "../../../../src/lib/ws/worker/portHost";
import { tokenOf, URL } from "./connectionHarness";
import { createFakeGateway, type FakeGatewayOptions } from "./fakeGateway";

type Of<T extends WorkerMessage["t"]> = Extract<WorkerMessage, { readonly t: T }>;

export class FakeTab implements PortLike {
  readonly sent: { readonly message: WorkerMessage; readonly transfer: ArrayBuffer[] }[] = [];
  /** The worker cannot write to a tab that is gone. */
  dead = false;
  private handler: ((data: unknown) => void) | undefined;
  /** The tokens it hands out, one a request. */
  issued = 0;

  constructor(private readonly answers: boolean) {}

  postMessage(message: unknown, transfer: ArrayBuffer[]): void {
    if (this.dead) throw new Error("the tab is gone");
    const posted = message as WorkerMessage;
    this.sent.push({ message: posted, transfer });
    if (posted.t === "tokenRequest" && this.answers) {
      const { req } = posted;
      queueMicrotask(() => {
        this.issued += 1;
        const result = {
          kind: "ok",
          accessToken: tokenOf(this.issued),
          expiresAtMs: Date.now() + 600_000,
        };
        this.say({ t: "token", req, result });
      });
    }
  }

  listen(handler: (data: unknown) => void): void {
    this.handler = handler;
  }

  /** One message from the tab to the worker. */
  say(message: object): void {
    this.handler?.(message);
  }

  /** What the worker posted of one type, oldest first. */
  of<T extends WorkerMessage["t"]>(t: T): Of<T>[] {
    return this.sent.flatMap(({ message }) => (message.t === t ? [message as Of<T>] : []));
  }

  last<T extends WorkerMessage["t"]>(t: T): Of<T> {
    const message = this.of(t).at(-1);
    if (message === undefined) throw new Error(`no ${t} message`);
    return message;
  }
}

export const CONNECT = {
  t: "connect",
  v: 1,
  wsUrl: URL,
  shell: "browser",
  locale: "en-GB",
  clientVersion: "1.0.0",
} as const;

export function hostHarness(
  gatewayOptions?: FakeGatewayOptions,
  overrides: Partial<PortHostOptions> = {},
) {
  vi.useFakeTimers();
  const gateway = createFakeGateway(gatewayOptions);
  const host = createPortHost({
    createSocket: gateway.createSocket,
    random: () => 0.5,
    ...overrides,
  });
  onTestFinished(() => host.dispose());
  /** A tab that has said `connect`; `answers: false` is one that never answers a token request. */
  const tab = (answers = true, connect: object = CONNECT): FakeTab => {
    const tab = new FakeTab(answers);
    host.attach(tab);
    tab.say(connect);
    return tab;
  };
  /** Moves the fake clock; the microtasks (a socket opening, a token, a flush) run on the way. */
  const advance = (ms = 0) => vi.advanceTimersByTimeAsync(ms);
  return { gateway, host, tab, advance };
}
