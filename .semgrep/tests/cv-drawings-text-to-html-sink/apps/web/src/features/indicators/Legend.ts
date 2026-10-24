// Outside the drawing paths: the rule stays quiet, so it cannot widen onto the rest of the app by mistake.
declare const label: string;

export function legend(): void {
  document.write(label); // ok: cv-drawings-text-to-html-sink
}
