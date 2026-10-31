// E11-X02: drawings stay with cv-drawings-text-to-html-sink; this rule does not look here.
declare const el: HTMLElement;
declare const text: string;

export function drawingsElsewhere(): void {
  el.innerHTML = text; // ok: cv-engine-html-sink
}
