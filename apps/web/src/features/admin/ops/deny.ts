/**
 * The admin area's withdrawal for the ops reads (BQ-10): a `403` on any of them means the session
 * lost the area, the shape of S01's denied read (SCR-154 N-2). The area's `deny(refId)` belongs to
 * #1023 (E42-S02 part B) by the orchestrator's ruling on the shared kit, so until it lands this hook
 * does nothing and the store that met the `403` stops alone and shows `AdminDenied`, as #1137's
 * inspector does.
 */
export type DenyHook = (refId: string | undefined) => void;

export const denyArea: DenyHook = () => undefined;
