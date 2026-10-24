// The literal path of the ticket: nothing creates it yet (E14-X03, #549).
declare const label: string;

export const note = <div dangerouslySetInnerHTML={{ __html: label }} />; // ruleid: cv-drawings-text-to-html-sink
