// The render worker lives in this folder (E11-T02): `protocol.ts` (the §6 messages and boundary
// validation), `runtime.ts` (the one render runtime both run modes use), `render-worker.ts` (the
// dedicated module worker entry) and `host.ts` (the main-thread host, the only DOM-side file
// here). This barrel stays empty: the package root exports §8 only (README BQ-2).
export {};
