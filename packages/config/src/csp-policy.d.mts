// Types for csp-policy.mjs: the single CSP policy builder (SR-112, C-12.10).
export const DEFAULT_BACKEND_ORIGIN: string;
export const CSP_REPORT_PATH: string;
export const CSP_REPORT_GROUP: string;
export function resolveBackendOrigin(raw: string): string;
export function parseTailnetHost(raw: unknown): string | null;
export function buildCspPolicy(options?: {
  backendOrigin?: string;
  tailnetHost?: string | null;
  surface?: "header" | "meta";
}): string;
export function buildReportingEndpoints(backendOrigin?: string): string;
