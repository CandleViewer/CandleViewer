/**
 * The T2 reason vocabulary (E09-D09 §3.1): the seven keys and their strings, verbatim. A screen never
 * writes its own reason string; it names one of these keys. A reason names a capability, never data.
 * None of these strings is marked PROPOSED in D09 §3.1; `rbac.read_only` is a step-2 refusal today and
 * becomes a T2 leg only once the session carries `read_only_until` (D09 §3.1, CG-2).
 */
export const RBAC_REASONS = {
  "rbac.permission": "Your role can't {verb}.",
  "rbac.owner_only": "Only the owner can {verb}.",
  "rbac.account": "This account isn't assigned to you.",
  "rbac.account_read_only": "You can view this account, not trade it.",
  "rbac.env": "Live trading isn't enabled for you.",
  "rbac.read_only": "Read-only after three wrong codes.",
  "rbac.view_as": "Read-only while viewing as {user}.",
} as const;

export type RbacReasonKey = keyof typeof RBAC_REASONS;

/** The fills each parametrised string takes: `{verb}` from the D09 §3.2 verb table, `{user}` the view-as target. */
export interface RbacReasonFills {
  readonly "rbac.permission": { readonly verb: string };
  readonly "rbac.owner_only": { readonly verb: string };
  readonly "rbac.view_as": { readonly user: string };
}

/** `[fills]` for a parametrised key, `[]` for a fixed string. */
export type RbacReasonArgs<K extends RbacReasonKey> = K extends keyof RbacReasonFills
  ? [fills: RbacReasonFills[K]]
  : [];

/** The reason sentence for `key`, with its `{…}` fills substituted. */
export function formatRbacReason<K extends RbacReasonKey>(
  key: K,
  ...[fills]: RbacReasonArgs<K>
): string {
  return fillRbacReason(key, fills);
}

/** Untyped core of `formatRbacReason`, for callers that already hold a key and its fills as a pair. */
export function fillRbacReason(
  key: RbacReasonKey,
  fills: Readonly<Record<string, string>> | undefined,
): string {
  return RBAC_REASONS[key].replace(/\{(\w+)\}/g, (match, name: string) => fills?.[name] ?? match);
}
