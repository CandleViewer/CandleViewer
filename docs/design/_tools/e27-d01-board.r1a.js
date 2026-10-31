/* E27-D01 research boards (#732), board script r1a: the round-3 PATCH of boards 04, 06 and 08.
 *
 * r1 drew the eight boards (sha256 in the memo's §1 register); r1a patches three of them in place, in the file
 * "E27-D01 research boards", page "E27-D01", and draws nothing new. Paste this file as the body of ONE Penpot plugin
 * call with that file open. It finds every shape by board id + shape name + its words, so it is idempotent: run it
 * until it answers `stable: true` (the first run sets the words; a text's wrapped height settles after the call, so
 * the second run measures it and re-lays the AD-11 row; the third changes nothing).
 *
 * Patches (the words are the memo's, docs/design/research/e27-key-custody.md, as folded in round 3):
 * - board 04: RA-7's response cell is restamped (OQ-5 ruled, #2701 ledger 1 row 64).
 * - board 06: the revoke dialog loses its bold lead line above the radios (the counts live only in CD-6's
 *   "Flatten first" sentence); the dialog's content moves up by the freed line and the dialog shrinks by the same.
 * - board 08: C10 quotes the catalogue's add-account line with its address elided; AD-11's two cells carry the
 *   merged memo's word ban again; a row that grows pushes every shape under it down and the board grows by the same.
 * - each patched board: the subtitle's source line and the footer name r1a.
 */
const PAGE_ID = "b96edf38-8e58-8006-8008-dd018bdbc198";
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
  "Nothing shows a secret again: no show, copy or download for a secret or a full key id; a key id is ... " +
  'plus its last 4 (CMP-034 without its toggle); secret fields are type=password with "value is write-only"; ' +
  'no control or label uses "reveal" or offers to show a secret, and if #896 defines the scope G-10 names as ' +
  "metadata only it renders as the permission list (G-10)";
const AD11_FAIL =
  'an eye or show toggle, first-4 plus last-4, a secret value, the word "reveal" or a label offering to show a ' +
  "secret appears in any frame";
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

// board 08: C10 and AD-11
const b08 = board(B08);
setText(
  one(b08, "td", (t) => t.startsWith('"IP whitelist: ')),
  C10,
  "08: C10",
);
const ad11 = one(b08, "td", (t) => t.startsWith("Nothing shows a secret again"));
const ad11f = one(b08, "td", (t) => t.startsWith("an eye or show toggle"));
for (const [s, txt] of [
  [ad11, AD11],
  [ad11f, AD11_FAIL],
]) {
  if (s.characters !== txt) {
    setText(s, txt, "08: AD-11 cell");
    s.growType = "auto-height"; // measured on the next run
  } else if (s.growType === "auto-height") {
    const lines = Math.max(1, Math.round(s.height / LINE));
    s.growType = "fixed";
    s.resize(s.width, BOX[lines]);
    changes.push(`08: AD-11 cell fixed at ${lines} lines`);
  } else {
    const lines = Math.max(1, Math.round((s.height - 14) / LINE));
    if (Math.abs(s.height - BOX[lines]) > 0.5) {
      s.resize(s.width, BOX[lines]);
      changes.push(`08: AD-11 cell set to ${lines} lines`);
    }
  }
}
restamp(b08);

// re-lay the AD-11 row: row = tallest td + ROW_PAD; everything under it moves by the difference
const pending = [ad11, ad11f].some((s) => s.growType === "auto-height");
const row = b08.children.filter(
  (s) => s.name === P + "table-row" && Math.abs(s.y + 8 - ad11.y) < 1 && s.type === "rectangle",
)[0];
let grew = 0;
if (!pending) {
  if (!row) throw new Error("08: AD-11 row not found");
  const cells = b08.children.filter((s) => s.name === P + "td" && Math.abs(s.y - ad11.y) < 1);
  const want = Math.max(...cells.map((s) => s.height)) + ROW_PAD;
  grew = Math.round(want - row.height);
  if (grew !== 0) {
    const oldBottom = row.y + row.height;
    for (const s of b08.children) if (s.y >= oldBottom - 0.5) s.y = s.y + grew;
    row.resize(row.width, row.height + grew);
    b08.resize(b08.width, b08.height + grew);
    changes.push("08: AD-11 row and board grew " + grew);
  }
}

return {
  stable: changes.length === 0 && !pending,
  changes,
  sizes: [b04, b06, b08].map((b) => ({ id: b.id, name: b.name, w: b.width, h: b.height })),
};
