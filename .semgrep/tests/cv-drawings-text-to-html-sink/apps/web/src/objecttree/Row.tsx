// The literal path of the ticket: nothing creates it yet (E14-X03, #549).
declare const label: string;

export const row = <li title={"Delete " + label}>{label}</li>; // ruleid: cv-drawings-text-to-html-sink
export const okRow = <li title={label}>{label}</li>; // ok: cv-drawings-text-to-html-sink
