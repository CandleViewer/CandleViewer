// E47-D09 board kit: the local icon seed. It is ../run/local-icons.js plus five glyphs, so run it in its place
// (README section 2, step 3) once in the per-set file "E47-D09 boards"; idempotent, existing icon/<name> are kept.
// The E47-D09 sheets bind seven icons: locked, close (shared seed) and check, info, more-horizontal, search, warning
// (added here; the kit's ICONS_OK allows more, unbound on these boards).
// Each glyph is the packages/ui Lucide source (lucide-static, ISC), path data unchanged:
//   locked          packages/ui/src/icons/source/lucide/lock.svg
//   arrow-up        packages/ui/src/icons/source/lucide/arrow-up.svg
//   arrow-down      packages/ui/src/icons/source/lucide/arrow-down.svg
//   close           packages/ui/src/icons/source/lucide/close.svg
//   drag-handle     packages/ui/src/icons/source/lucide/drag-handle.svg
//   check           packages/ui/src/icons/source/lucide/check.svg
//   info            packages/ui/src/icons/source/lucide/info.svg
//   more-horizontal packages/ui/src/icons/source/lucide/more-horizontal.svg
//   warning         packages/ui/src/icons/source/lucide/warning.svg
//   search          packages/ui/src/icons/source/lucide/search.svg
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
  info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
  "more-horizontal":
    '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
  warning:
    '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  search: '<path d="m21 21-4.34-4.34"/><circle cx="11" cy="11" r="8"/>',
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
  b.y = -2000;
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
