/** Thin REST client for the E09-S06 first-run checklist (state is always server-evaluated). */

import { apiFetch } from "../../lib/http/csrfFetch";

export type StepState = "ok" | "pending" | "blocked" | "error" | "not_applicable";
export interface ChecklistItem {
  readonly key: string;
  readonly state: StepState;
  readonly reason: string | null;
  readonly unblock_at: string | null;
  readonly action_route: string | null;
}
export interface Checklist {
  readonly complete: boolean;
  readonly dismissed: boolean;
  readonly items: readonly ChecklistItem[];
}

const BASE = "/api/v1/onboarding/checklist";

export async function fetchChecklist(): Promise<Checklist | null> {
  try {
    const res = await apiFetch(BASE);
    if (!res.ok) return null;
    return (await res.json()) as Checklist;
  } catch {
    return null;
  }
}

export async function dismissChecklist(): Promise<boolean> {
  try {
    return (await apiFetch(`${BASE}/dismiss`, { method: "POST" })).ok;
  } catch {
    return false;
  }
}

/** "Xh Ym" until `unblockAt` (UTC), floored to the minute; "0h 0m" once reached. */
export function formatCountdown(unblockAt: string, now: Date): string {
  const ms = Math.max(0, new Date(unblockAt).getTime() - now.getTime());
  const minutes = Math.floor(ms / 60_000);
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}
