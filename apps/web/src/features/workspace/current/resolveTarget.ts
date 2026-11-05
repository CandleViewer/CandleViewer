/**
 * `/terminal[/:layoutId]` resolved to a workspace (E15-S03 #476; BQ-02 (a), `12` R-100 / R-101): a
 * layout's UUID opens its workspace (one no workspace holds is not found); anything else the
 * last-used one, else the default, else the first (`listWorkspaces` answers in `sort_order`). The
 * last-used record is ids only (SR-129, SR-E15-14), per user id; a storage that throws reads as none.
 */
import { getShellState } from "../../../shell/bootstrap/store";
import * as api from "../api/workspacesApi";

export interface LastUsed {
  readonly workspaceId: string;
  readonly layoutId: string | null;
}

const PREFIX = "cv.workspace.last.";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const isId = (v: unknown): v is string => typeof v === "string" && UUID.test(v);
const field = (v: unknown, key: string): unknown =>
  typeof v === "object" && v !== null ? Reflect.get(v, key) : undefined;

type Store = Pick<Storage, "getItem" | "setItem">;
const device = (): Store | null => (typeof localStorage === "undefined" ? null : localStorage);

/** The signed-in user's id from `/me`, read defensively: a reply without `user` keys nothing. */
export function sessionUserId(): string | null {
  const id = field(getShellState().me?.user, "id");
  return isId(id) ? id : null;
}

export function readLastUsed(userId: string, storage = device()): LastUsed | null {
  try {
    const raw: unknown = JSON.parse(storage?.getItem(PREFIX + userId) ?? "null");
    const [workspaceId, layoutId] = [field(raw, "workspaceId"), field(raw, "layoutId")];
    return isId(workspaceId) ? { workspaceId, layoutId: isId(layoutId) ? layoutId : null } : null;
  } catch {
    return null;
  }
}

export function writeLastUsed(userId: string, value: LastUsed, storage = device()): void {
  try {
    const { workspaceId, layoutId } = value;
    storage?.setItem(PREFIX + userId, JSON.stringify({ workspaceId, layoutId }));
  } catch {
    // A full or refused storage keeps the previous record: last-used is a convenience.
  }
}

export type Resolution =
  | ({ readonly kind: "open" } & LastUsed)
  | { readonly kind: "empty" }
  | { readonly kind: "failed"; readonly failure: api.ApiFailure };

export interface ResolveDeps {
  readonly list: (signal?: AbortSignal) => Promise<api.ApiResult<api.Workspace[]>>;
  readonly get: (id: string, signal?: AbortSignal) => Promise<api.ApiResult<api.WorkspaceDetail>>;
}

const DEFAULT_DEPS: ResolveDeps = { list: api.listWorkspaces, get: api.getWorkspace };

export async function resolveTerminal(
  target: string,
  last: LastUsed | null,
  deps: ResolveDeps = DEFAULT_DEPS,
  signal?: AbortSignal, // the route's: leaving it cancels the remaining GETs
): Promise<Resolution> {
  const listed = await deps.list(signal);
  if (!listed.ok) return { kind: "failed", failure: listed.failure };
  const all = listed.value;
  const remembered = all.find((w) => w.id === last?.workspaceId);
  if (isId(target)) {
    // The last-used workspace first, then the rest in order: one GET per id, at most 32. A 429 ends
    // the probe with its wait (never queued, SR-E15-04); a layout no workspace holds is not found.
    const rest = all.filter((w) => w !== remembered);
    for (const ws of remembered === undefined ? all : [remembered, ...rest]) {
      const detail = await deps.get(ws.id, signal);
      if (detail.ok && detail.value.layouts.some((l) => l.id === target)) {
        return { kind: "open", workspaceId: ws.id, layoutId: target };
      }
      if (!detail.ok && detail.failure.kind !== "not_found") {
        return { kind: "failed", failure: detail.failure };
      }
    }
    return { kind: "failed", failure: { kind: "not_found" } };
  }
  if (remembered !== undefined) {
    return { kind: "open", workspaceId: remembered.id, layoutId: last?.layoutId ?? null };
  }
  const chosen = all.find((w) => w.is_default) ?? all[0];
  return chosen === undefined
    ? { kind: "empty" }
    : { kind: "open", workspaceId: chosen.id, layoutId: null };
}
