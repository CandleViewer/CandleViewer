// The worker, as a tab sees its port: what the tab posts is recorded, what the worker says is injected.
import type { PortLike } from "../../../../src/lib/ws/port/endpoint";

export class FakePort implements PortLike {
  readonly posted: { t: string; [key: string]: unknown }[] = [];
  readonly transfers: ArrayBuffer[][] = [];
  readonly order: string[] = [];
  private handler: ((data: unknown) => void) | undefined;
  postMessage(message: unknown, transfer: ArrayBuffer[]): void {
    this.order.push("post");
    this.posted.push(message as { t: string });
    this.transfers.push(transfer);
  }
  listen(handler: (data: unknown) => void): void {
    this.order.push("listen");
    this.handler = handler;
  }
  say(message: unknown): void {
    this.handler?.(message);
  }
  of(t: string) {
    return this.posted.filter((m) => m.t === t);
  }
}
