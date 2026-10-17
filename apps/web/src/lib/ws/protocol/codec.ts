// E17-T04 S1: encode client frames, decode server frames, validate CVWB bodies. All of it parses
// UNTRUSTED input, so `decodeFrame` and `validateCvwb` never throw: a bad frame is a typed
// `frame_malformed` (23 10.2). D11: no generated TS validators exist, so the guards check the
// envelope and the payload fields the client reads; Ajv stays test-only.
import * as P from "@candleviewer/protocol";
import * as F from "./frames";

export type DecodeDiagnostic =
  "envelope" | "payload" | "cvwb" | "unsupported_body_kind" | "unsupported_format_version";

/** A frame that cannot be trusted. `code` is the wire code; `diagnostic` the local detail (3.4). */
export interface WsDecodeError {
  readonly t: "decode_error";
  readonly code: "frame_malformed";
  readonly diagnostic: DecodeDiagnostic;
  /** Safe to log: never carries payload bytes or a token. */
  readonly message: string;
  /** The topic the envelope named, if any, so the caller can resync it. */
  readonly ch?: string | undefined;
}

interface Head {
  readonly id?: string | undefined;
  readonly ch?: string | undefined;
  readonly ts?: number | undefined;
  readonly wt?: number | undefined;
  readonly rs?: string | undefined;
}

type ControlType = keyof F.ControlPayloads;

export type ControlFrame = Head &
  (
    | { [T in ControlType]: { readonly t: T; readonly p: F.ControlPayloads[T] } }[ControlType]
    | { readonly t: "ping" | "pong"; readonly p?: F.HeartbeatPayload | undefined }
  );

/** `j`: the structured payload. `b64`: the raw bytes of a CVWB body, not yet validated. */
export type DataBody =
  { readonly e: "j"; readonly p: unknown } | { readonly e: "b64"; readonly bytes: ArrayBuffer };

export interface DataFrame extends Head {
  readonly t: "snap" | "d";
  readonly ch: string;
  /** `null` on an intermediate chunk of a chunked snapshot (3.6). */
  readonly s: number | null;
  readonly ts: number;
  readonly meta?: F.SnapMeta | undefined;
  readonly body: DataBody;
}

export type Inbound = ControlFrame | DataFrame;

const malformed = (
  diagnostic: DecodeDiagnostic,
  message: string,
  ch?: string | undefined,
): WsDecodeError => ({ t: "decode_error", code: "frame_malformed", diagnostic, message, ch });

export const encodeFrame = (frame: F.ClientFrame): string => JSON.stringify(frame);

const CVWB_DECODERS = [
  P.decodeBookSnapshot,
  P.decodeBookDelta,
  P.decodeTrades,
  P.decodeBars,
  P.decodeFootprint,
  P.decodeHeatmapColumn,
];

export type CvwbResult =
  { readonly ok: true; readonly header: P.BinaryFrameHeader } | WsDecodeError;

/**
 * C10: magic, `(body_kind, format_version)` and the length are checked by the E17-T02 decoders
 * (SR-128). The decoded records are dropped: the worker transfers the raw buffer (D13).
 */
export function validateCvwb(buf: ArrayBuffer | ArrayBufferView): CvwbResult {
  const view = ArrayBuffer.isView(buf) ? buf : new Uint8Array(buf);
  try {
    const decode = CVWB_DECODERS[P.parseBinaryFrameHeader(view).bodyKind - 1];
    if (decode === undefined) throw new P.BinaryFrameError("no decoder", "unsupported_body_kind");
    return { ok: true, header: decode(view).header };
  } catch (e) {
    if (!(e instanceof P.BinaryFrameError)) return malformed("cvwb", "binary body is undecodable");
    return malformed(e.code === "frame_malformed" ? "cvwb" : e.code, e.message);
  }
}

const isObj = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);
const isStr = (v: unknown): v is string => typeof v === "string";
const isInt = (v: unknown): v is number =>
  typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
const isSeq = (v: unknown): v is number | null => v === null || isInt(v);
const optional = (v: unknown, ok: (x: unknown) => boolean): boolean => v === undefined || ok(v);

/** Strict on purpose: the kill switch is safety state (C12), so an inexact shape is refused. */
const isKillSwitch = (v: unknown): boolean =>
  isObj(v) &&
  typeof v["engaged"] === "boolean" &&
  (v["scope"] === "global" || v["scope"] === "accounts") &&
  optional(v["exchange_account_ids"], (a) => Array.isArray(a) && a.every(isStr));

/** Fields each control payload must carry (`path:kind`): the ones the client reads. */
const REQUIRED: Readonly<Record<ControlType, string>> = {
  welcome: `connection_id:string heartbeat.interval_ms:number heartbeat.timeout_ms:number
    limits.max_subscriptions:number limits.max_topics_per_request:number limits.min_throttle_ms:number`,
  auth_ok: "user_id:string token_expires_at_ms:number roles:array account_scope:array",
  permission_change: "roles:array account_scope:array",
  sub_ok: "results:array",
  unsub_ok: "results:array",
  ctl_ok: "effective:object",
  revoked: "reason:string",
  err: "code:string",
  bye: "code:number reason:string",
};

const isControl = (t: unknown): t is ControlType => isStr(t) && Object.hasOwn(REQUIRED, t);

function hasFields(spec: string, p: unknown): boolean {
  return spec.split(/\s+/).every((entry) => {
    const [path = "", kind = ""] = entry.split(":");
    const v = path.split(".").reduce<unknown>((o, k) => (isObj(o) ? o[k] : undefined), p);
    if (kind === "array") return Array.isArray(v);
    if (kind === "object") return isObj(v);
    return typeof v === kind && (kind !== "number" || Number.isFinite(v));
  });
}

function payloadOk(t: ControlType, p: unknown): boolean {
  if (!isObj(p) || !hasFields(REQUIRED[t], p)) return false;
  if (t === "auth_ok") return optional(p["kill_switch"], isKillSwitch);
  if (t !== "sub_ok" && t !== "unsub_ok") return true;
  const results = p["results"];
  const isResult = (r: unknown) => isObj(r) && isStr(r["ch"]) && typeof r["ok"] === "boolean";
  return Array.isArray(results) && results.every(isResult);
}

/** Standard base64 into a fresh buffer the caller owns (so it can be transferred), else `undefined`. */
function fromBase64(text: string): ArrayBuffer | undefined {
  if (text.length % 4 !== 0) return undefined;
  let bin: string;
  try {
    bin = atob(text);
  } catch {
    return undefined;
  }
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

function readHead(o: Record<string, unknown>): Head | undefined {
  const { id, ch, ts, wt, rs } = o;
  const isId = (v: unknown) => isStr(v) && v.length <= F.MAX_ID_LENGTH;
  const ok = [
    optional(id, isId),
    optional(ch, isStr),
    optional(ts, isInt),
    optional(wt, isInt),
    optional(rs, isStr),
  ];
  // Cast: each field was just verified to be absent or of its declared type.
  return ok.every(Boolean) ? ({ id, ch, ts, wt, rs } as Head) : undefined;
}

/**
 * Decodes one `cv.v1.json` message (D3). Unknown fields are ignored (2.3); anything else wrong is
 * `frame_malformed`. `e: "b64"` becomes an owned `ArrayBuffer`: validate it with `validateCvwb`.
 */
export function decodeFrame(data: unknown): Inbound | WsDecodeError {
  if (typeof data !== "string") return malformed("envelope", "binary message on cv.v1.json");
  let raw: unknown;
  try {
    raw = JSON.parse(data);
  } catch {
    return malformed("envelope", "message is not valid JSON");
  }
  if (!isObj(raw)) return malformed("envelope", "message is not a JSON object");
  const topic = isStr(raw["ch"]) ? raw["ch"] : undefined;
  const fail = (message: string, diagnostic: DecodeDiagnostic = "envelope") =>
    malformed(diagnostic, message, topic);
  const head = readHead(raw);
  if (head === undefined) return fail("envelope field has the wrong type");
  const t = raw["t"];
  const p = raw["p"];

  if (t === "ping" || t === "pong" || isControl(t)) {
    const ok = t === "ping" || t === "pong" ? optional(p, isObj) : payloadOk(t, p);
    // Cast: the fields the client reads were verified above; the rest of `p` is carried through.
    return ok ? ({ ...head, t, p } as Inbound) : fail(`${t} payload is malformed`, "payload");
  }
  if (t !== "snap" && t !== "d") return fail("unknown or client-only frame type");

  const { s, e = "j", meta } = raw;
  const { ch, ts } = head;
  const invalid = !isSeq(s) || (t === "d" && s === null) || !optional(meta, isObj);
  if (ch === undefined || ts === undefined || p === undefined || invalid) {
    return fail("data frame is missing or has an invalid field");
  }
  const bytes = e === "b64" && isStr(p) ? fromBase64(p) : undefined;
  // `b` is the MessagePack form of a binary body; on `cv.v1.json` it must be `b64`.
  if (e !== "j" && bytes === undefined) return fail("payload is not a valid j or b64 body");
  const body: DataBody = bytes === undefined ? { e: "j", p } : { e: "b64", bytes };
  // Cast: every `SnapMeta` field is optional and read defensively by its consumer.
  return { ...head, t, ch, s, ts, meta: meta as F.SnapMeta | undefined, body };
}
