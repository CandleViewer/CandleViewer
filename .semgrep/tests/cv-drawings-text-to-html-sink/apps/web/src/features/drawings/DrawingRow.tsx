// Fixtures for cv-drawings-text-to-html-sink: the JSX sinks of a drawing's stored text (E14-X03, #549).
declare const React: { createElement(...a: unknown[]): unknown };
declare const d: { id: string; label: string; kind: string; color: string };
declare const depth: number;
declare function t(key: string, vars?: Record<string, string>): string;

export const html = <div dangerouslySetInnerHTML={{ __html: d.label }} />; // ruleid: cv-drawings-text-to-html-sink
export const props = React.createElement("div", { dangerouslySetInnerHTML: { __html: d.label } }); // ruleid: cv-drawings-text-to-html-sink
export const name = <li aria-label={"Drawing " + d.label}>x</li>; // ruleid: cv-drawings-text-to-html-sink
export const nameT = <li aria-label={`${d.kind} ${d.label}`}>x</li>; // ruleid: cv-drawings-text-to-html-sink
export const desc = <li aria-description={`Made by ${d.label}`}>x</li>; // ruleid: cv-drawings-text-to-html-sink
export const tip = <button title={"Delete " + d.label} />; // ruleid: cv-drawings-text-to-html-sink
export const link = <a href={`/drawings/${d.id}`}>x</a>; // ruleid: cv-drawings-text-to-html-sink
export const img = <img src={"/icons/" + d.kind + ".svg"} alt="" />; // ruleid: cv-drawings-text-to-html-sink
export const css = <li style={`color:${d.color}`}>x</li>; // ruleid: cv-drawings-text-to-html-sink
export const frame = <iframe srcDoc={d.label} title="note" />; // ruleid: cv-drawings-text-to-html-sink
export const page = <iframe srcDoc="<p>note</p>" title="note" />; // ruleid: cv-drawings-text-to-html-sink
export const made2 = React.createElement("iframe", { srcDoc: d.label }); // ruleid: cv-drawings-text-to-html-sink
export const made = React.createElement("li", { "aria-label": `Drawing ${d.label}` }); // ruleid: cv-drawings-text-to-html-sink
export const made3 = React.createElement("a", { href: "/d/" + d.id }); // ruleid: cv-drawings-text-to-html-sink

// Where a naive "any attribute built from a variable" rule would misfire:
export const okText = <li aria-label={d.label}>{d.label}</li>; // ok: cv-drawings-text-to-html-sink
export const okLiteral = <button title="Delete" aria-label="Delete drawing" />; // ok: cv-drawings-text-to-html-sink
export const okCall = <li title={t("drawing.row", { label: d.label })}>x</li>; // ok: cv-drawings-text-to-html-sink
export const okStyle = <li style={{ paddingLeft: `${depth * 16}px` }}>x</li>; // ok: cv-drawings-text-to-html-sink
export const okData = <li data-row={`row-${d.id}`}>x</li>; // ok: cv-drawings-text-to-html-sink
export const okConst = <a href="/drawings" title={`Drawings`} />; // ok: cv-drawings-text-to-html-sink
export const okFrame = <iframe src="about:blank" title="note" />; // ok: cv-drawings-text-to-html-sink
export const okMade = React.createElement("li", { "data-row": `row-${d.id}` }); // ok: cv-drawings-text-to-html-sink
