// E17-T04 S1 (C-6.1): the web client's wire frames. Payload types alias the generated
// `@candleviewer/protocol` WS types (C-4.16). The generated module declares `SnapMeta`, `Error`
// and `KillSwitch` twice, so those are taken from the payload that carries them, not by name.
import type { generated } from "@candleviewer/protocol";

export type HelloPayload = generated.ws.CvWsV1HelloSchemaJson;
export type AuthPayload = generated.ws.CvWsV1AuthSchemaJson;
export type SubPayload = generated.ws.CvWsV1SubSchemaJson;
export type UnsubPayload = generated.ws.CvWsV1UnsubSchemaJson;
/**
 * 13.6 `ctl.schema.json` has `minProperties: 1` but the generated type admits `{}`; this one does
 * not. A property set to `undefined` is refused too (`exactOptionalPropertyTypes`): JSON drops it,
 * which would put an empty `ctl` on the wire.
 */
type AtLeastOne<T> = { [K in keyof T]-?: Required<Pick<T, K>> & Partial<T> }[keyof T];
export type CtlPayload = AtLeastOne<generated.ws.CvWsV1CtlSchemaJson>;
export type ResyncPayload = generated.ws.CvWsV1ResyncSchemaJson;
export type HeartbeatPayload = generated.ws.PingPongPayloads;
export type SubOptions = generated.ws.Options;
export type SystemUpdate = generated.ws.System;
export type SnapMeta = NonNullable<generated.ws.CandleViewerWSEnvelope["meta"]>;
export type KillSwitchPayload = NonNullable<SystemUpdate["kill_switch"]>;

/** The payload of each server -> client control frame (23 3.1); `t` is the key. */
export interface ControlPayloads {
  welcome: generated.ws.CvWsV1WelcomeSchemaJson;
  auth_ok: generated.ws.CvWsV1AuthOkSchemaJson;
  permission_change: generated.ws.CvWsV1PermissionChangeSchemaJson;
  sub_ok: generated.ws.CvWsV1SubOkSchemaJson;
  unsub_ok: generated.ws.CvWsV1UnsubOkSchemaJson;
  ctl_ok: generated.ws.CvWsV1CtlOkSchemaJson;
  revoked: generated.ws.CvWsV1RevokedSchemaJson;
  err: NonNullable<generated.ws.CvWsV1SubOkSchemaJson["results"][number]["error"]>;
  bye: generated.ws.CvWsV1ByeSchemaJson;
}

/** `Sec-WebSocket-Protocol` offer. D3: msgpack joins only once it can be decoded (#2886). */
export const SUBPROTOCOLS = ["cv.v1.json"] as const;
export const CLIENT_NAME = "candleviewer-web";
/** 23 13.1: the server drops a longer correlation `id`, so its reply could not be matched. */
export const MAX_ID_LENGTH = 64;
type Capability = NonNullable<HelloPayload["capabilities"]>[number];
export const CAPABILITIES: readonly Capability[] = [
  "binary_book",
  "binary_bars",
  "binary_trades",
  "binary_footprint",
  "binary_heatmap",
  "coalescing",
  "replay",
  "partial_snapshots",
];

type Frame<T extends string, P> = { readonly t: T; readonly id: string; readonly p: P };
type ChannelFrame<T extends string, P> = Frame<T, P> & { readonly ch: string };

/** Client -> server frames (23 3.1). */
export type ClientFrame =
  | Frame<"hello", HelloPayload>
  | Frame<"auth", AuthPayload>
  | Frame<"sub", SubPayload>
  | Frame<"unsub", UnsubPayload>
  | ChannelFrame<"ctl", CtlPayload>
  | ChannelFrame<"resync", ResyncPayload>
  | Frame<"ping" | "pong", HeartbeatPayload>;

/** `c-<n>` ids, unique per source. A factory, not a module counter: no shared mutable state. */
export function createIdSource(): () => string {
  let n = 0;
  return () => `c-${(n += 1)}`;
}

type HelloArgs = Pick<HelloPayload, "client_version" | "shell" | "locale" | "clock_ms">;

export const hello = (id: string, args: HelloArgs): ClientFrame => ({
  t: "hello",
  id,
  p: {
    client: CLIENT_NAME,
    protocol: "cv.v1",
    encodings: ["binary", "structured"],
    capabilities: [...CAPABILITIES],
    ...args,
  },
});

/** The token goes into this one frame only: never logged, stored or put in a URL (4.3). */
export const auth = (
  id: string,
  token: string,
  envs?: AuthPayload["environments"],
): ClientFrame => ({
  t: "auth",
  id,
  p: { access_token: token, ...(envs && { environments: envs }) },
});

export const sub = (id: string, p: SubPayload): ClientFrame => ({ t: "sub", id, p });
export const unsub = (id: string, topics: UnsubPayload["topics"]): ClientFrame => ({
  t: "unsub",
  id,
  p: { topics },
});
export const ctl = (id: string, ch: string, p: CtlPayload): ClientFrame => ({
  t: "ctl",
  id,
  ch,
  p,
});
export const resync = (id: string, ch: string, p: ResyncPayload): ClientFrame => ({
  t: "resync",
  id,
  ch,
  p,
});
export const ping = (id: string, ms: number): ClientFrame => ({
  t: "ping",
  id,
  p: { client_ms: ms },
});
/** `id` echoes the server's `ping` id (9.1). */
export const pong = (id: string, ms: number): ClientFrame => ({
  t: "pong",
  id,
  p: { client_ms: ms },
});
