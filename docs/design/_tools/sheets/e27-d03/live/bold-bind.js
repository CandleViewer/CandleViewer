// E27-D03 post-render step (boards review round 2, B-1): bind `font.weight.bold` (700) on the critical state's BLOCKED
// label and the LIVE pill's word over `type.ui.label` (BQ-6 (3), §3.1). cvsheet v4.3 has no font-weight field, so the
// sheets keep the BOLD fallback and this runs once per board after rendering, through the Penpot plugin bridge.
// Set BOARD to a board-name prefix such as 'E27-D03 / 04'. Applying a token that is already bound unbinds it, so only
// unbound texts are touched; read back with `bound` before exporting.
const BOARD = globalThis.BOARD;
const pg = penpot.currentFile.pages.find((p) => p.name.startsWith("E27-D03 Accounts"));
const tok = penpot.library.local.tokens.sets
  .flatMap((s) => s.tokens)
  .find((t) => t.name === "font.weight.bold");
if (!tok) return { abort: "no font.weight.bold token in the file" };
const root = pg.root.children.find((b) => b.name.startsWith(BOARD));
if (!root) return { abort: "no board " + BOARD };
const isBold = (s) =>
  s.type === "text" && (/^BLOCKED/.test(s.characters) || s.characters === "LIVE");
const todo = penpotUtils.findShapes((s) => isBold(s) && !(s.tokens || {}).fontWeight, root);
tok.applyToShapes(todo, ["fontWeight"]);
const bound = penpotUtils
  .findShapes(isBold, root)
  .filter((s) => (s.tokens || {}).fontWeight === "font.weight.bold").length;
return { board: root.name, applied: todo.length, bound };
