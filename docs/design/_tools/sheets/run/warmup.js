// After a tab reload: make the browser load the fonts the boards use before the first section draws (first-section
// texts drawn right after a reload came out blank or in a fallback serif: E32-D02 08 / 13 heads, E16-D02 17).
// Creates one temporary text per weight on the current page, waits, and removes them. Touches nothing else.
const made = [];
try {
  for (const w of ["400", "500", "600", "700"]) {
    const t = penpot.createText("Warm up Inter " + w + " 0123456789");
    if (!t) continue;
    t.name = "warmup (temporary)";
    t.fontFamily = "Inter";
    t.fontWeight = w;
    t.fontSize = "14";
    t.x = -100000;
    t.y = -100000 - made.length * 40;
    made.push(t);
  }
  const m = penpot.createText("Warm up mono 0123456789");
  if (m) {
    m.name = "warmup (temporary)";
    m.fontFamily = "JetBrains Mono";
    m.fontSize = "13";
    m.x = -100000;
    m.y = -99000;
    made.push(m);
  }
  await new Promise((r) => setTimeout(r, 2500));
} finally {
  for (const t of made) {
    try {
      t.remove();
    } catch (e) {
      /* ignore */
    }
  }
}
return { warmed: made.length };
