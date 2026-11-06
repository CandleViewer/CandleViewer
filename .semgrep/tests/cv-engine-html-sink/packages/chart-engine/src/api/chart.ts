// E11-X02 (F-07): the facade too.
declare const host: HTMLElement;
declare const message: string;

export function errorBad(): void {
  host.setHTMLUnsafe(message); // ruleid: cv-engine-html-sink
}

export function errorOk(): void {
  host.textContent = message; // ok: cv-engine-html-sink
}
