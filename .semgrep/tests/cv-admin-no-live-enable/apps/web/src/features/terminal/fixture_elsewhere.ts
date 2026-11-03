// Fixtures: no client write turns the live gate on anywhere in the app, while the posture rule
// reads the admin feature only; a URL built from the imported key in the call is a URL naming it.
import { LIVE_GATE_FLAG } from "../admin/flags/keys";
declare function apiFetch(url: string, init?: object): Promise<Response>;
declare function urlFor(key: string): string;

const LIVE = "/api/v1/admin/feature-flags/trading.live_enabled";
export const SUMMARY = "/api/v1/admin/security/summary"; // ok: cv-admin-no-live-enable

export async function elsewhere(): Promise<Response[]> {
  return [
    await apiFetch(LIVE, { method: "PUT" }), // ruleid: cv-admin-no-live-enable
    await apiFetch(urlFor(LIVE_GATE_FLAG), { method: "PUT" }), // ruleid: cv-admin-no-live-enable
    await apiFetch(urlFor(LIVE_GATE_FLAG), { method: "GET" }), // ok: cv-admin-no-live-enable
  ];
}
