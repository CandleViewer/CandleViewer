import { apiFetch } from "../../lib/http/csrfFetch";
import { parsePreferences, type A11yPreferences } from "./model";

const URL = "/api/v1/settings";

export async function loadPreferences(): Promise<A11yPreferences> {
  const r = await apiFetch(URL);
  if (!r.ok) throw new Error(`settings ${r.status}`);
  const body = (await r.json()) as { accessibility?: unknown };
  return parsePreferences(body.accessibility);
}

/** Partial deep-merge PATCH of the `accessibility` subtree only (`22` `/settings`). */
export async function savePreferences(patch: Partial<A11yPreferences>): Promise<A11yPreferences> {
  const r = await apiFetch(URL, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ accessibility: patch }),
  });
  if (!r.ok) throw new Error(`settings ${r.status}`);
  const body = (await r.json()) as { accessibility?: unknown };
  return parsePreferences(body.accessibility);
}
