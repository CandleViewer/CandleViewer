export const HARNESS_MARKER: RegExp;
export function findHarnessLeaks(files: readonly { name: string; text: string }[]): string[];
