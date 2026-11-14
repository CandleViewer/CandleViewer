// Fixtures for cv-admin-no-live-enable-ts in the flag console: no write that may turn the live
// gate on leaves the client, as a flag write, a map of values or a request to a URL naming it;
// and the key keeps its name, so another name for it (any binding of an expression holding it,
// an array, a subscript, a call passing it beside a value) is a finding too.
import { LIVE_GATE_FLAG as GATE } from "./keys"; // ruleid: cv-admin-no-live-enable
declare function holdFlagWrite(write: object): object;
declare function holdRequest(method: string, url: string, headers: object, body: string): object;
declare function sendHeld(held: object): Promise<Response>;
declare function apiFetch(url: string, init?: object): Promise<Response>;
declare function specOf(key: string): object;
declare function setFlag(...args: unknown[]): void;
declare function urlFor(key: string): string;
declare function holdFlagWrites(values: object): object;
declare const byKey: Record<string, unknown>;
declare const flags: { LIVE_GATE_FLAG: string };
declare const next: boolean;
declare const key: string;
declare const init: RequestInit;
declare const method: string;

const FLAGS = "/api/v1/admin/feature-flags/";
const LIVE_URL = "/api/v1/admin/feature-flags/trading.live_enabled";
export const LIVE_GATE_FLAG = "trading.live_enabled"; // ok: cv-admin-no-live-enable

export async function turnsItOn(): Promise<unknown[]> {
  holdFlagWrite({ key: LIVE_GATE_FLAG, value: true }); // ruleid: cv-admin-no-live-enable
  holdFlagWrite({ key: "trading.live_enabled", value: next }); // ruleid: cv-admin-no-live-enable
  holdFlagWrite({ value: true, key: flags.LIVE_GATE_FLAG }); // ruleid: cv-admin-no-live-enable
  await apiFetch(LIVE_URL, { method: "PATCH", body: "{}" }); // ruleid: cv-admin-no-live-enable
  await fetch(`${FLAGS}${LIVE_GATE_FLAG}`, { method: "put" }); // ruleid: cv-admin-no-live-enable
  holdRequest("PUT", FLAGS + encodeURI(LIVE_GATE_FLAG), {}, ""); // ruleid: cv-admin-no-live-enable
  await sendHeld({ method: "PUT", url: FLAGS + LIVE_GATE_FLAG }); // ruleid: cv-admin-no-live-enable
  const request = new Request(LIVE_URL, { method: "POST" }); // ruleid: cv-admin-no-live-enable
  const values = { [LIVE_GATE_FLAG]: true }; // ruleid: cv-admin-no-live-enable
  const patch = { "trading.live_enabled": true }; // ruleid: cv-admin-no-live-enable
  const gate = LIVE_GATE_FLAG; // ruleid: cv-admin-no-live-enable
  const other = flags.LIVE_GATE_FLAG; // ruleid: cv-admin-no-live-enable
  await apiFetch(LIVE_URL, init); // ruleid: cv-admin-no-live-enable
  await fetch(`${FLAGS}${LIVE_GATE_FLAG}`, init); // ruleid: cv-admin-no-live-enable
  await fetch(`${FLAGS}${LIVE_GATE_FLAG}`, { method }); // ruleid: cv-admin-no-live-enable
  await apiFetch(LIVE_URL, { method: "DELETE" }); // ruleid: cv-admin-no-live-enable
  let held = LIVE_GATE_FLAG; // ruleid: cv-admin-no-live-enable
  var kept = flags.LIVE_GATE_FLAG; // ruleid: cv-admin-no-live-enable
  const { LIVE_GATE_FLAG: renamed } = flags; // ruleid: cv-admin-no-live-enable
  const url = `${FLAGS}${LIVE_GATE_FLAG}`; // ruleid: cv-admin-no-live-enable
  const blocked = { [LIVE_GATE_FLAG]: { group: "gated" } }; // ruleid: cv-admin-no-live-enable
  const spec = specOf(flags.LIVE_GATE_FLAG); // ruleid: cv-admin-no-live-enable
  held = `${FLAGS}${LIVE_GATE_FLAG}`; // ruleid: cv-admin-no-live-enable
  setFlag(LIVE_GATE_FLAG, next); // ruleid: cv-admin-no-live-enable
  setFlag(next, flags.LIVE_GATE_FLAG); // ruleid: cv-admin-no-live-enable
  byKey[LIVE_GATE_FLAG] = next; // ruleid: cv-admin-no-live-enable
  holdFlagWrites(Object.fromEntries([[LIVE_GATE_FLAG, next]])); // ruleid: cv-admin-no-live-enable
  await fetch(urlFor(LIVE_GATE_FLAG), { method: "PUT" }); // ruleid: cv-admin-no-live-enable
  return [request, values, patch, gate, other, GATE, held, kept, renamed, url, blocked, spec];
}

export async function leavesItAlone(): Promise<unknown[]> {
  holdFlagWrite({ key: LIVE_GATE_FLAG, value: false }); // ok: cv-admin-no-live-enable
  holdFlagWrite({ key: "trading.one_click", value: true }); // ok: cv-admin-no-live-enable
  await fetch(`${FLAGS}${LIVE_GATE_FLAG}`); // ok: cv-admin-no-live-enable
  await apiFetch(LIVE_URL, { method: "GET" }); // ok: cv-admin-no-live-enable
  await apiFetch(LIVE_URL, { method: "head" }); // ok: cv-admin-no-live-enable
  await apiFetch(`${FLAGS}trading.one_click`, { method: "PUT" }); // ok: cv-admin-no-live-enable
  setFlag(false, LIVE_GATE_FLAG); // ok: cv-admin-no-live-enable
  byKey[LIVE_GATE_FLAG] = false; // ok: cv-admin-no-live-enable
  await fetch(urlFor(LIVE_GATE_FLAG)); // ok: cv-admin-no-live-enable
  if (key === LIVE_GATE_FLAG) throw new Error("the live gate's"); // ok: cv-admin-no-live-enable
  const note = "PUT trading.live_enabled: true"; // ok: cv-admin-no-live-enable
  // holdFlagWrite({ key: LIVE_GATE_FLAG, value: true }) in a comment // ok: cv-admin-no-live-enable
  await apiFetch(`${FLAGS}trading.one_click`, init); // ok: cv-admin-no-live-enable
  return [specOf(LIVE_GATE_FLAG), note];
}
