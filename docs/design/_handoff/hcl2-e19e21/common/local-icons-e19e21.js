// The repo's run/local-icons.js glyphs plus the ones the three E19/E21 kits use: check, chevron-down, chevron-right,
// info, more-horizontal, warning (Lucide triangle-alert), danger (octagon-alert), pending, refresh (the last two from
// packages/ui/src/icons/source/lucide/*.svg). The E47 transport's glyph set (search, copy unused here). Run it after run/local-icons.js.
// Create LOCAL icon components (path "icon") in the open per-set file from Lucide (ISC) glyphs: 24 grid, 1.5 stroke.
// Idempotent: existing icon/<name> components are kept.
const ICONS = {
  locked:
    '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  "arrow-up": '<path d="m5 12 7-7 7 7"/><path d="M12 19V5"/>',
  "arrow-down": '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
  close: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  "drag-handle":
    '<circle cx="9" cy="12" r="1"/><circle cx="9" cy="5" r="1"/><circle cx="9" cy="19" r="1"/><circle cx="15" cy="12" r="1"/><circle cx="15" cy="5" r="1"/><circle cx="15" cy="19" r="1"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  "chevron-down": '<path d="m6 9 6 6 6-6"/>',
  "chevron-right": '<path d="m9 18 6-6-6-6"/>',
  info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
  "more-horizontal": '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
  warning: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  danger: '<path d="M12 16h.01"/><path d="M12 8v4"/><path d="M15.312 2a2 2 0 0 1 1.414.586l4.688 4.688A2 2 0 0 1 22 8.688v6.624a2 2 0 0 1-.586 1.414l-4.688 4.688a2 2 0 0 1-1.414.586H8.688a2 2 0 0 1-1.414-.586l-4.688-4.688A2 2 0 0 1 2 15.312V8.688a2 2 0 0 1 .586-1.414l4.688-4.688A2 2 0 0 1 8.688 2z"/>',
  pending: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
  search: '<path d="m21 21-4.34-4.34"/><circle cx="11" cy="11" r="8"/>',
  copy: '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
  refresh:
    '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
};
const out = {};
let i = 0;
for (const [name, body] of Object.entries(ICONS)) {
  const old = penpot.library.local.components.find((c) => c.path === "icon" && c.name === name);
  if (old) {
    const m = old.mainInstance();
    m.clipContent = false;
    for (const g0 of m.children || []) {
      g0.constraintsHorizontal = "scale";
      g0.constraintsVertical = "scale";
      for (const k of g0.children || []) {
        k.constraintsHorizontal = "scale";
        k.constraintsVertical = "scale";
      }
    }
    const st = [m];
    while (st.length) {
      const x = st.pop();
      if (x.name === "base-background") {
        x.remove();
        continue;
      }
      if (x.children) for (const k of x.children) st.push(k);
    }
    out[name] = "kept+cleaned";
    continue;
  }
  const svg =
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#000000" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
    body +
    "</svg>";
  const g = penpot.createShapeFromSvg(svg);
  const b = penpot.createBoard();
  b.name = name;
  b.resize(24, 24);
  b.fills = [];
  b.x = -2000 - 40 * i;
  b.y = -2080; // a second row: run/local-icons.js's glyphs sit at y -2000
  b.appendChild(g);
  g.x = b.x;
  g.y = b.y;
  // the SVG import adds a 24x24 'base-background' rect that inherits the stroke: remove it; never clip the glyph
  const st = [g];
  while (st.length) {
    const x = st.pop();
    if (x.name === "base-background") {
      x.remove();
      continue;
    }
    if (x.children) for (const k of x.children) st.push(k);
  }
  b.clipContent = false;
  // scale with the instance: cvlib resizes icons to size.icon (12/16 px); left/top constraints would leave a 24 px glyph clipped
  g.constraintsHorizontal = "scale";
  g.constraintsVertical = "scale";
  for (const k of g.children || []) {
    k.constraintsHorizontal = "scale";
    k.constraintsVertical = "scale";
  }
  const comp = penpot.library.local.createComponent([b]);
  comp.name = name;
  comp.path = "icon";
  out[name] = "created";
  i++;
}
return { file: penpot.currentFile.name, icons: out };
