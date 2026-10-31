// E11-X02 (F-07, CE-T11): the DOM mirror (E11-S13) and the host write text, never markup.
declare const doc: Document;
declare const row: HTMLElement;
declare const label: string;
declare const range: Range;

export function mirrorBad(): void {
  row.innerHTML = label; // ruleid: cv-engine-html-sink
  row["outerHTML"] = `<b>${label}</b>`; // ruleid: cv-engine-html-sink
  row.insertAdjacentHTML("beforeend", label); // ruleid: cv-engine-html-sink
  range.createContextualFragment(label); // ruleid: cv-engine-html-sink
  doc.write(label); // ruleid: cv-engine-html-sink
  Object.assign(row, { innerHTML: label }); // ruleid: cv-engine-html-sink
  row.setAttribute("onclick", label); // ruleid: cv-engine-html-sink
  new DOMParser().parseFromString(label, "text/html"); // ruleid: cv-engine-html-sink
}

declare const name: string;
declare const sheet: CSSStyleSheet;

export function mirrorReviewBad(): void {
  row.setAttribute(name, label); // ruleid: cv-engine-html-sink
  row.setAttributeNS(null, "href", label); // ruleid: cv-engine-html-sink
  row.outerHTML += label; // ruleid: cv-engine-html-sink
  Reflect.set(row, "innerHTML", label); // ruleid: cv-engine-html-sink
  new DOMParser().parseFromString(label, "image/svg+xml"); // ruleid: cv-engine-html-sink
  doc.createElement("script"); // ruleid: cv-engine-html-sink
  (row as HTMLAnchorElement).href = label; // ruleid: cv-engine-html-sink
  location.assign(label); // ruleid: cv-engine-html-sink
  window.open(label); // ruleid: cv-engine-html-sink
  row.style.cssText = label; // ruleid: cv-engine-html-sink
  sheet.insertRule(label); // ruleid: cv-engine-html-sink
  row.setAttribute("style", label); // ruleid: cv-engine-html-sink
  row.onclick = "alert(1)"; // ruleid: cv-engine-html-sink
  row.onmouseover = `go(${label})`; // ruleid: cv-engine-html-sink
  row.onerror = "report(" + label + ")"; // ruleid: cv-engine-html-sink
  row.onload = label.length > 0 ? "a()" : "b()"; // ruleid: cv-engine-html-sink
}

export function mirrorOk(): void {
  doc.createElement("div"); // ok: cv-engine-html-sink
  row.style.cssText = "width: 4px"; // ok: cv-engine-html-sink
  row.textContent = label; // ok: cv-engine-html-sink
  row.setAttribute("aria-label", label); // ok: cv-engine-html-sink
  row.style.setProperty("--cv-width", "4px"); // ok: cv-engine-html-sink
  Object.assign(row.style, { width: "4px" }); // ok: cv-engine-html-sink
  row.onclick = () => undefined; // ok: cv-engine-html-sink
  // A handler function is code the bundle shipped; a string inside its body is not the handler.
  row.onerror = () => fail(new Error("load failed")); // ok: cv-engine-html-sink
  row.onload = () => log(`loaded ${label}`); // ok: cv-engine-html-sink
  // ok: cv-engine-html-sink
  row.onabort = function () {
    return "aborted";
  };
  doc.createTextNode(label); // ok: cv-engine-html-sink
}
