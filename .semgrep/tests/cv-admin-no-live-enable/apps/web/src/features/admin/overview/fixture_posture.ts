// Fixtures for cv-admin-no-posture-verdict-ts: no admin component reads the posture summary
// before E43-S02 mounts SCR-137; a comment naming it, the placeholder's route and its copy are
// not reads.
declare function getSecuritySummary(): Promise<unknown>;
declare function read(schema: unknown): void;
declare const client: { getSecuritySummary(): Promise<unknown>; readSummary(): Promise<unknown> };
declare const schemas: Record<string, unknown>;
declare const operations: Record<string, unknown>;
declare const api: string;

export async function reads(): Promise<void> {
  await fetch("/api/v1/admin/security/summary"); // ruleid: cv-admin-no-live-enable
  await fetch(`${api}/admin/security/summary?fresh=1`); // ruleid: cv-admin-no-live-enable
  await getSecuritySummary(); // ruleid: cv-admin-no-live-enable
  await client.getSecuritySummary(); // ruleid: cv-admin-no-live-enable
  read(schemas["SecuritySummary"]); // ruleid: cv-admin-no-live-enable
  read(operations["getSecuritySummary"]); // ruleid: cv-admin-no-live-enable
}

// `getSecuritySummary` is not mounted (CG-7). // ok: cv-admin-no-live-enable
export const ROUTE = "/admin/security"; // ok: cv-admin-no-live-enable
export const AUDIT = "/admin/audit"; // ok: cv-admin-no-live-enable
export const LINE = "Security posture checks ship in R4 (E43)"; // ok: cv-admin-no-live-enable
export const NOTE = "getSecuritySummary is not mounted"; // ok: cv-admin-no-live-enable
export const summary = (): Promise<unknown> => client.readSummary(); // ok: cv-admin-no-live-enable
