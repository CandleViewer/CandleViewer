const START = 0;
const LEN = 45000;
const b = storage.pngbuf;
if (!b) return { err: "no buffer" };
const end = Math.min(b.length, START + LEN);
let s = "";
for (let i = START; i < end; i++) s += String.fromCharCode(b[i]);
return { total: b.length, start: START, end, b64: btoa(s) };
