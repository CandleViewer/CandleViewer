// E11-X02 (F-07): and the worker's main-thread host.
declare const frame: HTMLIFrameElement;
declare const html: string;

export function frameBad(): void {
  frame.srcdoc = html; // ruleid: cv-engine-html-sink
}

export function frameOk(): void {
  frame.title = html; // ok: cv-engine-html-sink
}
