// The engine draws a drawing's label as glyphs, never as markup (E14-X03, #549).
declare const ctx: { fillText(text: string, x: number, y: number): void };
declare const range: Range;
declare const label: string;

export function draw(): void {
  range.createContextualFragment(label); // ruleid: cv-drawings-text-to-html-sink
  ctx.fillText(label, 0, 0); // ok: cv-drawings-text-to-html-sink
}
