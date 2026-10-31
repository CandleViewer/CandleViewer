/* E27-D01 research boards (#732), board script r1a: the round-3 PATCH of boards 03, 04, 06 and 08.
 *
 * r1 drew the eight boards (sha256 in the memo's §1 register); r1a patches four of them in place, in the file
 * "E27-D01 research boards", page "E27-D01", and draws nothing new. Paste this file as the body of ONE Penpot plugin
 * call with that file open. It finds every shape by board id + shape name + its words, so it is idempotent: run it
 * until it answers `stable: true` (the first run sets the words; a text's wrapped height settles after the call, so
 * the second run measures it and re-lays its row; the third changes nothing).
 *
 * Patches (the words are the memo's, docs/design/research/e27-key-custody.md, as folded in round 3):
 * - board 03: CP-1's trap cell carries the merged memo's "reveal" wording again.
 * - board 04: RA-7's response cell is restamped (OQ-5 ruled, #2701 ledger 1 row 64).
 * - board 06: the revoke dialog loses its bold lead line above the radios (the counts live only in CD-6's
 *   "Flatten first" sentence); the dialog's content moves up by the freed line and the dialog shrinks by the same.
 * - board 08: C10 quotes the catalogue's add-account line with its address elided; AD-11's two cells, IM-7's two
 *   cells and AD-16's fail cell carry the merged memo's "reveal" wording again (the boards follow the merged memo);
 *   a row whose height changes moves every shape under it by the same and the board resizes by the same.
 * - each patched board: the subtitle's source line and the footer name r1a.
 */
const PAGE_ID = "b96edf38-8e58-8006-8008-dd018bdbc198";
const B03 = "b96edf38-8e58-8006-8008-dd01ad82a294";
const B04 = "b96edf38-8e58-8006-8008-dd01b4ea5c0d";
const B06 = "b96edf38-8e58-8006-8008-dd01c624a1cc";
const B08 = "b96edf38-8e58-8006-8008-dd01d5b72f9e";
const P = "E27-D01 / ";
const LINE = 17.94; // 13 px × 1.38
const BOX = [0, 32, 50, 67, 85, 103]; // a fixed td box per wrapped line count (r1's heights)
const ROW_PAD = 16; // a table row is its tallest td plus 16 px (r1's rule)

const RA7 =
  "state whether the rule touches a rotation (OQ-5, RULED: it binds a new sub-account's first key, " +
  "not a new key on an existing account)";
const C10 = '"IP whitelist: … [ + add ]" (14:2449)';
const AD11 =
  "No reveal anywhere: no show, copy or download for a secret or a full key id; a key id is ... " +
  'plus its last 4 (CMP-034 without its toggle); secret fields are type=password with "value is write-only"; ' +
  'no control or label uses "reveal", and if #896 defines reveal-scope as ' +
  "metadata only it renders as the permission list (G-10)";
const AD11_FAIL =
  'an eye or reveal toggle, first-4 plus last-4, a secret value or the word "reveal" appears in any frame';
const IM7 = "No reveal control anywhere";
const IM7_WHY = "CMP-034 listed with its reveal toggle (14:2462, 14:2473; 15:355-357) → AD-11";
const AD16_FAIL =
  "a bare spinner, a fake staged reveal, or a lock and a reason on the busy control";
const CP1_TRAP = "a fresh code will reveal it (step-up read as an unlock)";
const SRC_OLD = "at 2b6993705c (blob 018ab03cbf), as folded in the boards PR";
const SRC_NEW = "as folded in the boards PR, round 3 (§1)";

const page = penpot.currentFile.pages.find((p) => p.id === PAGE_ID);
if (!page) throw new Error("page E27-D01 not found");
// the plugin writes only to the active page: open it and stop; the next run patches
if (penpot.currentPage.id !== PAGE_ID) {
  penpot.openPage(page);
  return { stable: false, changes: ["opened page E27-D01"], sizes: [] };
}
const board = (id) => {
  const b = page.root.children.find((s) => s.id === id && s.type === "board");
  if (!b) throw new Error("board missing: " + id);
  return b;
};
const kids = (b, name) => b.children.filter((s) => s.name === P + name);
const one = (b, name, test) => {
  const hit = kids(b, name).filter((s) => s.type === "text" && test(s.characters));
  if (hit.length !== 1) throw new Error(`${b.name}: ${name} matched ${hit.length}`);
  return hit[0];
};
const changes = [];
const setText = (s, txt, why) => {
  if (s.characters !== txt) {
    s.characters = txt;
    changes.push(why);
  }
};
const restamp = (b) => {
  const sub = one(b, "board-subtitle", (t) => t.includes("board script r1"));
  const t = sub.characters
    .replace(SRC_OLD, SRC_NEW)
    .replace(/board script r1a?$/, "board script r1a");
  setText(sub, t, b.name + ": subtitle r1a");
  const foot = one(b, "footer", (t) => /· r1a?$/.test(t));
  setText(foot, foot.characters.replace(/· r1a?$/, "· r1a"), b.name + ": footer r1a");
};

// board 04: RA-7's response cell
const b04 = board(B04);
setText(
  one(b04, "td", (t) => t.startsWith("state whether the rule touches a rotation")),
  RA7,
  "04: RA-7",
);
restamp(b04);

// board 06: drop the revoke dialog's lead line; close the gap inside the dialog
const b06 = board(B06);
const lead = kids(b06, "mock-text").filter(
  (s) =>
    s.type === "text" && s.characters === "cancel 3 orders, stop its algos and close 2 positions",
);
if (lead.length > 1) throw new Error("06: lead line matched " + lead.length);
if (lead.length === 1) {
  const dlg = kids(b06, "dialog").filter((s) => Math.abs(s.x - lead[0].x + 16) < 1)[0];
  if (!dlg) throw new Error("06: revoke dialog not found");
  const gap = 42; // the freed line: lead top → first radio row top (975 → 1017)
  const top = lead[0].y + lead[0].height;
  const bottom = dlg.y + dlg.height;
  lead[0].remove();
  for (const s of b06.children) {
    if (s.id === dlg.id) continue;
    if (s.x >= dlg.x && s.x + s.width <= dlg.x + dlg.width && s.y >= top && s.y < bottom)
      s.y = s.y - gap;
  }
  dlg.resize(dlg.width, dlg.height - gap);
  changes.push("06: lead line removed, dialog content up " + gap);
}
restamp(b06);

// board 08: C10; then the reveal-wording cells of boards 08 and 03
const b08 = board(B08);
setText(
  one(b08, "td", (t) => t.startsWith('"IP whitelist: ')),
  C10,
  "08: C10",
);
// a cell whose words change: set them, let the height settle (auto-height), then fix it at r1's box
const fit = (b, s, txt, why) => {
  if (s.characters !== txt) {
    setText(s, txt, why);
    s.growType = "auto-height"; // measured on the next run
  } else if (s.growType === "auto-height") {
    const lines = Math.max(1, Math.round(s.height / LINE));
    s.growType = "fixed";
    s.resize(s.width, BOX[lines]);
    changes.push(`${why} fixed at ${lines} lines`);
  } else {
    const lines = Math.max(1, Math.round((s.height - 14) / LINE));
    if (Math.abs(s.height - BOX[lines]) > 0.5) {
      s.resize(s.width, BOX[lines]);
      changes.push(`${why} set to ${lines} lines`);
    }
  }
};
// re-lay a cell's row: row = tallest td + ROW_PAD; everything under it moves by the difference
const relay = (b, cell, why) => {
  const row = b.children.filter(
    (s) => s.name === P + "table-row" && Math.abs(s.y + 8 - cell.y) < 1 && s.type === "rectangle",
  )[0];
  if (!row) throw new Error(why + ": row not found");
  const cells = b.children.filter((s) => s.name === P + "td" && Math.abs(s.y - cell.y) < 1);
  const grew = Math.round(Math.max(...cells.map((s) => s.height)) + ROW_PAD - row.height);
  if (grew === 0) return;
  if (b.id !== B08) throw new Error(why + ": row height would change by " + grew); // checked, never shifted
  const oldBottom = row.y + row.height;
  for (const s of b.children) if (s.y >= oldBottom - 0.5) s.y = s.y + grew;
  row.resize(row.width, row.height + grew);
  b.resize(b.width, b.height + grew);
  changes.push(why + ": row and board moved " + grew);
};
const starts =
  (...heads) =>
  (t) =>
    heads.some((h) => t.startsWith(h));
const cellPatches = [
  [b08, starts("No reveal anywhere", "Nothing shows a secret again"), AD11, "08: AD-11 cell"],
  [
    b08,
    starts("an eye or reveal toggle", "an eye or show toggle"),
    AD11_FAIL,
    "08: AD-11 fail cell",
  ],
  [b08, (t) => t === IM7 || t === "No show-again control anywhere", IM7, "08: IM-7 cell"],
  [b08, starts("CMP-034 listed with its "), IM7_WHY, "08: IM-7 conflict cell"],
  [b08, starts("a bare spinner, a fake staged "), AD16_FAIL, "08: AD-16 fail cell"],
];
const b03 = board(B03);
cellPatches.push([b03, starts("a fresh code will "), CP1_TRAP, "03: CP-1 trap cell"]);
const hits = cellPatches.map(([b, test, txt, why]) => [b, one(b, "td", test), txt, why]);
for (const [b, s, txt, why] of hits) fit(b, s, txt, why);
const pending = hits.some(([, s]) => s.growType === "auto-height");
if (!pending) for (const [b, s, , why] of hits) relay(b, s, why);
restamp(b03);
restamp(b08);

return {
  stable: changes.length === 0 && !pending,
  changes,
  sizes: [b03, b04, b06, b08].map((b) => ({ id: b.id, name: b.name, w: b.width, h: b.height })),
};
