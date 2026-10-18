// E17-T04 S5f (ADR-0005, D13; 23 4.1; C8, C9, C11, C12): the tab's end of the port, and the client the app holds. It sends the
// worker what the tab wants (consumers, panes, focus, whether the page is seen), answers its requests for the access token
// (the only message that carries one, and nothing here keeps it), and gives the app what the worker posts: the connection
// state (a transition reaches every subscriber at once, the kill switch in the task its message arrives in), the `system`
// updates, and per consumer a bounded queue behind `read()`. Rendering follows the display, never the feed: an arrival
// only fills a queue and drops the latest of what a handle reads into the frame scheduler, which applies it on the next
// animation frame. Nothing is applied from the arrival path, and a data message never notifies a state subscriber.
import type {
  ConsumerSpec,
  PaneVisibility,
  TokenResult,
  TokenSource,
  TopicFrame,
  TopicHandle,
  WsClient,
} from "../api";
import { throttleIndicator, type LatencyIndicator } from "../../telemetry/latencyIndicator";
import { RESYNC_WINDOW_MS } from "../core/resyncGuard";
import { platformTimers, type Timers } from "../policy/timers";
import type { PortLike } from "../port/endpoint";
import { createFrameQueue, type FrameQueue, type QueueLimits } from "../port/frameQueue";
import {
  parseWorkerMessage,
  PORT_PROTOCOL_VERSION,
  type ClientMessage,
  type DataMessage,
  type Shell,
  type TokenRequestMessage,
  type WsDiagnostics,
} from "../port/messages";
import type { SystemUpdate } from "../protocol/frames";
import { INITIAL_WS_STATE, reduce } from "../state/reducer";
import type { TopicStatus, WsState } from "../state/types";
import { createFrameScheduler, type FrameMark } from "./frameScheduler";

/**
 * How long the worker has to answer a `connect` with the state, and a `consume` with its first `data` (it does so within a flush,
 * 8 ms). A worker that refuses a message says nothing (what it counts is its own), so silence this long is the answer: the
 * connection reads offline, a consumer reads revoked.
 */
export const HOST_WAIT_MS = 5_000;

/** What the client needs of the page it lives in. */
export interface Page {
  hidden(): boolean;
  /** `listener` hears each change of `hidden()`; the returned function stops it. */
  watch(listener: () => void): () => void;
  /** `listener` hears the page go away: a tab that is closed cannot say `stop` afterwards, and a shared worker is not told. */
  onExit(listener: () => void): () => void;
}

export const documentPage = (): Page =>
  typeof document === "undefined"
    ? { hidden: () => false, watch: () => () => undefined, onExit: () => () => undefined }
    : {
        hidden: () => document.visibilityState === "hidden",
        watch: (listener) => {
          document.addEventListener("visibilitychange", listener);
          return () => document.removeEventListener("visibilitychange", listener);
        },
        onExit: (listener) => {
          window.addEventListener("pagehide", listener);
          return () => window.removeEventListener("pagehide", listener);
        },
      };

export interface WsClientOptions {
  readonly wsUrl: string;
  readonly tokens: TokenSource;
  readonly shell: Shell;
  readonly locale: string;
  readonly clientVersion: string;
  /** The tab's end of the port to the worker (see `openWorkerPort`); a test puts a fake or a `MessageChannel` here. */
  readonly port: PortLike;
  /** A `system` update, the moment it arrives: the kill switch does not wait for a frame. */
  readonly onSystem?: ((update: SystemUpdate) => void) | undefined;
  /** `fe_ws_decode_ms` (D8): the time the worker spent decoding each frame. */
  readonly telemetry?: { recordDecode(ms: number): void } | undefined;
  /** The age of the newest frame of a rendered batch, once a second at most (budget #3). */
  readonly onLatency?: ((indicator: LatencyIndicator) => void) | undefined;
  /** Budget #3 stage marks of the frame scheduler. */
  readonly mark?: ((name: FrameMark, atMs: number) => void) | undefined;
  readonly page?: Page | undefined;
  readonly timers?: Partial<Timers> | undefined;
  /** The wall clock the frames' `ts` are read against. Defaults to `Date.now`. */
  readonly wallClock?: (() => number) | undefined;
  readonly raf?: ((callback: (frameTimeMs: number) => void) => number) | undefined;
  readonly caf?: ((handle: number) => void) | undefined;
  /** The bounds of the queue behind each `read()`. */
  readonly queueLimits?: QueueLimits | undefined;
}

export interface WsClientHandle extends WsClient {
  /** The worker's counters as of its last `diag` (D8): in memory, never exported. */
  diagnostics(): WsDiagnostics | undefined;
}

/** What a handle reads, as of the last animation frame that had news of it. */
interface View {
  readonly status: TopicStatus;
  readonly effective: Readonly<Record<string, unknown>>;
  readonly source: "live" | "replay";
}
interface Slot extends View {
  /** The `ts` of the newest frame of the message, if it had one. */
  readonly ts: number | undefined;
}

interface Consumer {
  readonly id: string;
  readonly ch: string;
  readonly rs: string | undefined;
  readonly queue: FrameQueue;
  view: View;
  /** Its queue overflowed: no delta extends anything until a baseline arrives. */
  waiting: boolean;
  /** The wait for the worker's first word about it. */
  answer: unknown;
  /** The wait for the snapshot it asked for (`waiting`): when it ends the `resync` is sent again. */
  reask: unknown;
}

const NOTHING: Readonly<Record<string, unknown>> = Object.freeze({});

/** What the worker reads of a token result and no more: a field the source adds (a refresh token, a user) stays in the tab. */
const picked = (result: TokenResult): TokenResult =>
  result.kind === "ok"
    ? { kind: "ok", accessToken: result.accessToken, expiresAtMs: result.expiresAtMs }
    : { kind: result.kind };

export function createWsClient(options: WsClientOptions): WsClientHandle {
  const { port, tokens } = options;
  const timers: Timers = { ...platformTimers, ...options.timers };
  const page = options.page ?? documentPage();
  const wallClock = options.wallClock ?? ((): number => Date.now());
  const consumers = new Map<string, Consumer>();
  const listeners = new Set<() => void>();
  let state: WsState = INITIAL_WS_STATE;
  let diag: WsDiagnostics | undefined;
  let stopped = false;
  let sequence = 0;
  let connectWait: unknown;

  const post = (message: ClientMessage): void => port.postMessage(message, []);

  /** An error of the app's own callback is raised on its own, and does not keep the client from going on. */
  const raise = (error: unknown): void =>
    timers.queueMicrotask(() => {
      throw error;
    });

  /** A subscriber that throws does not keep the others from hearing. */
  function notify(): void {
    for (const listener of [...listeners]) {
      try {
        listener();
      } catch (error) {
        raise(error);
      }
    }
  }

  const indicate =
    options.onLatency === undefined ? undefined : throttleIndicator(options.onLatency, wallClock);
  const scheduler = createFrameScheduler<Slot>({
    raf: options.raf,
    caf: options.caf,
    mark: options.mark,
    render: (batch) => {
      let newest: number | undefined;
      for (const [id, { ts, ...view }] of batch) {
        const consumer = consumers.get(id);
        if (consumer === undefined) continue; // released since
        consumer.view = view;
        // a replay frame's `ts` is the time it was recorded (23 11): it says nothing of how late the feed is
        if (ts !== undefined && consumer.rs === undefined) newest = Math.max(newest ?? ts, ts);
      }
      // the worker's clock is ahead of ours by `clockSkewMs` (`welcome`): the age of a frame is the difference of the two clocks
      if (newest !== undefined) indicate?.(wallClock() + (diag?.clockSkewMs ?? 0) - newest);
    },
  });

  function stopAsking(consumer: Consumer): void {
    if (consumer.reask !== undefined) timers.clearTimeout(consumer.reask);
    consumer.reask = undefined;
  }

  /**
   * Asks the worker for a snapshot. A `resync` it refuses (the tab has voided this `ch` too often in the window) gets no answer,
   * so while none has come the request is made again each window, when the count may have room again. Bounded by that count.
   */
  function askForSnapshot(consumer: Consumer): void {
    stopAsking(consumer);
    post({ t: "resync", id: consumer.id });
    consumer.reask = timers.setTimeout(() => askForSnapshot(consumer), RESYNC_WINDOW_MS);
  }

  function voided(consumer: Consumer): void {
    consumer.waiting = true;
    consumer.queue.push({ kind: "reset", reason: "overflow" }); // the reader clears its state, ahead of the snapshot
    askForSnapshot(consumer);
  }

  function enqueue(consumer: Consumer, frame: TopicFrame): void {
    if (frame.kind === "snap") consumer.waiting = false;
    else if (frame.kind === "d" && consumer.waiting) return; // it extends a baseline that is gone
    if (consumer.queue.push(frame) === "overflow") voided(consumer);
  }

  function onData(message: DataMessage): void {
    const consumer = consumers.get(message.id);
    if (consumer === undefined) return; // released since: its frames are for nobody
    if (consumer.answer !== undefined) timers.clearTimeout(consumer.answer);
    consumer.answer = undefined;
    let ts: number | undefined;
    for (const frame of message.frames) {
      if (frame.kind !== "reset") {
        try {
          options.telemetry?.recordDecode(frame.decodeMs);
        } catch (error) {
          raise(error); // the app's aggregator: its bug does not drop the frames of the message
        }
        ts = frame.ts;
      }
      enqueue(consumer, frame);
    }
    if (!consumer.waiting || message.status === "revoked") stopAsking(consumer); // a snapshot came, or none will
    const { effective, source } = message;
    // resyncing until the snapshot (the worker may not have heard the `resync` yet), unless it revoked the stream
    const status = consumer.waiting && message.status !== "revoked" ? "resyncing" : message.status;
    scheduler.post(consumer.id, { status, effective, source, ts });
  }

  function answerToken(request: TokenRequestMessage): void {
    // a source that throws (from `invalidate` too), rather than says `unavailable`, is the same answer; the token is in this closure and nowhere else
    void Promise.resolve()
      .then(() => {
        if (request.invalidate) tokens.invalidate();
        return tokens.getToken();
      })
      .then(picked)
      .catch((): TokenResult => ({ kind: "unavailable" }))
      .then((result) => {
        if (!stopped) post({ t: "token", req: request.req, result });
      });
  }

  function onMessage(data: unknown): void {
    if (stopped) return;
    const message = parseWorkerMessage(data);
    if (message === undefined) return; // not the worker's: nothing to answer, and nobody to tell
    switch (message.t) {
      case "state":
        if (connectWait !== undefined) timers.clearTimeout(connectWait);
        connectWait = undefined;
        state = message.state;
        notify();
        break;
      case "system":
        try {
          options.onSystem?.(message.update);
        } catch (error) {
          raise(error);
        }
        break;
      case "data":
        onData(message);
        break;
      case "tokenRequest":
        answerToken(message);
        break;
      case "diag":
        diag = message.diag;
        break;
    }
  }

  function release(consumer: Consumer): void {
    if (consumers.get(consumer.id) !== consumer) return;
    consumers.delete(consumer.id);
    if (consumer.answer !== undefined) timers.clearTimeout(consumer.answer);
    stopAsking(consumer);
    consumer.queue.clear();
    if (!stopped) post({ t: "release", id: consumer.id });
  }

  function handleOf(consumer: Consumer): TopicHandle {
    return {
      ch: consumer.ch,
      rs: consumer.rs,
      read: () => consumer.queue.drain(),
      get effective() {
        return consumer.view.effective;
      },
      get status() {
        return consumer.view.status;
      },
      get source() {
        return consumer.view.source;
      },
      release: () => release(consumer),
    };
  }

  const unwatch = [
    page.watch(() => post({ t: "visibility", hidden: page.hidden() })),
    page.onExit(() => client.stop()),
  ];
  port.listen(onMessage);
  // The waits are armed before the posts: a port that answers inside `postMessage` must find the wait it ends.
  connectWait = timers.setTimeout(() => {
    connectWait = undefined;
    state = reduce(state, { type: "offline", cause: "fatal" });
    notify();
  }, HOST_WAIT_MS);
  post({
    t: "connect",
    v: PORT_PROTOCOL_VERSION,
    wsUrl: options.wsUrl,
    shell: options.shell,
    locale: options.locale,
    clientVersion: options.clientVersion,
  });
  post({ t: "visibility", hidden: page.hidden() });

  const client: WsClientHandle = {
    consume(spec: ConsumerSpec, rs?: string): TopicHandle {
      sequence += 1;
      const consumer: Consumer = {
        id: `c${sequence}`,
        ch: spec.ch,
        rs,
        queue: createFrameQueue(options.queueLimits),
        view: {
          status: stopped ? "revoked" : "pending",
          effective: NOTHING,
          source: rs === undefined ? "live" : "replay",
        },
        waiting: false,
        answer: undefined,
        reask: undefined,
      };
      if (stopped) return handleOf(consumer); // nothing is served any more
      consumers.set(consumer.id, consumer);
      // armed before the post, like the connect's: an answer inside `postMessage` finds the wait it ends
      consumer.answer = timers.setTimeout(() => {
        consumer.answer = undefined;
        consumer.view = { ...consumer.view, status: "revoked" }; // refused: the worker says nothing of what it refuses
      }, HOST_WAIT_MS);
      post({
        t: "consume",
        id: consumer.id,
        ch: spec.ch,
        pane: spec.paneId,
        priority: spec.priority,
        ...(rs !== undefined && { rs }),
        ...(spec.opts !== undefined && { opts: spec.opts }),
      });
      return handleOf(consumer);
    },
    setPane(
      paneId: string,
      visibility: PaneVisibility,
      size?: { cssWidth: number; dpr: number },
    ): void {
      if (stopped) return;
      post({
        t: "pane",
        id: paneId,
        visibility,
        ...(size !== undefined && { cssWidth: size.cssWidth, dpr: size.dpr }),
      });
    },
    focusPane(paneId: string | null): void {
      if (!stopped) post({ t: "focus", id: paneId });
    },
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
    diagnostics: () => diag,
    stop() {
      if (stopped) return;
      post({ t: "stop" });
      stopped = true;
      state = reduce(state, { type: "offline", cause: "fatal" }); // a mounted UI must not keep order entry on:
      notify(); // the last thing the subscribers hear, before they go
      for (const stop of unwatch) stop();
      scheduler.stop();
      for (const consumer of consumers.values()) {
        if (consumer.answer !== undefined) timers.clearTimeout(consumer.answer);
        stopAsking(consumer);
        consumer.queue.clear();
      }
      consumers.clear();
      listeners.clear();
      if (connectWait !== undefined) timers.clearTimeout(connectWait);
      connectWait = undefined;
    },
  };
  return client;
}
