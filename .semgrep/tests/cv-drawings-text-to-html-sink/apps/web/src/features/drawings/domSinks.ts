// Fixtures for cv-drawings-text-to-html-sink: the DOM-API sinks of a drawing's stored text (E14-X03, #549).
declare const el: HTMLElement;
declare const link: HTMLAnchorElement;
declare const frame: HTMLIFrameElement;
declare const sheet: CSSStyleSheet;
declare const range: Range;
declare const stream: { write(chunk: string): void };
declare const label: string;
declare const css: string;

export function sinks(): void {
  el.innerHTML = label; // ruleid: cv-drawings-text-to-html-sink
  el.innerHTML += label; // ruleid: cv-drawings-text-to-html-sink
  el.outerHTML = label; // ruleid: cv-drawings-text-to-html-sink
  el.insertAdjacentHTML("beforeend", label); // ruleid: cv-drawings-text-to-html-sink
  document.write(label); // ruleid: cv-drawings-text-to-html-sink
  document.writeln(label); // ruleid: cv-drawings-text-to-html-sink
  frame.contentDocument.write(label); // ruleid: cv-drawings-text-to-html-sink
  range.createContextualFragment(label); // ruleid: cv-drawings-text-to-html-sink
  frame.srcdoc = label; // ruleid: cv-drawings-text-to-html-sink
  frame.setAttribute("srcdoc", label); // ruleid: cv-drawings-text-to-html-sink
  el.style.cssText = css; // ruleid: cv-drawings-text-to-html-sink
  el.style.cssText += css; // ruleid: cv-drawings-text-to-html-sink
  sheet.insertRule(css); // ruleid: cv-drawings-text-to-html-sink
  el.setAttribute("style", css); // ruleid: cv-drawings-text-to-html-sink
  el.setAttribute("aria-label", "Drawing " + label); // ruleid: cv-drawings-text-to-html-sink
  el.setAttribute("title", `Drawing ${label}`); // ruleid: cv-drawings-text-to-html-sink
  link.href = "/d/" + label; // ruleid: cv-drawings-text-to-html-sink
  link.title = `Drawing ${label}`; // ruleid: cv-drawings-text-to-html-sink
}

// The text-node forms the message points to, and what a naive rule on the same words would flag:
export function safe(): void {
  stream.write(label); // ok: cv-drawings-text-to-html-sink
  document.createDocumentFragment(); // ok: cv-drawings-text-to-html-sink
  el.textContent = label; // ok: cv-drawings-text-to-html-sink
  el.innerText = label; // ok: cv-drawings-text-to-html-sink
  el.replaceChildren(); // ok: cv-drawings-text-to-html-sink
  el.setAttribute("aria-label", label); // ok: cv-drawings-text-to-html-sink
  el.setAttribute("title", label); // ok: cv-drawings-text-to-html-sink
  el.setAttribute("data-row", `row-${label}`); // ok: cv-drawings-text-to-html-sink
  el.style.cssText = ""; // ok: cv-drawings-text-to-html-sink
  el.style.setProperty("--drawing-color", css); // ok: cv-drawings-text-to-html-sink
  el.style.color = css; // ok: cv-drawings-text-to-html-sink
  sheet.insertRule("li { color: red }"); // ok: cv-drawings-text-to-html-sink
  el.setAttribute("style", "display: none"); // ok: cv-drawings-text-to-html-sink
}
