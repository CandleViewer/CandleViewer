/* E12-D05 — RELAYOUT follow-up (E29-D02 r7's helper, its constants changed for #241 r1, copied from #319 r1).
 *
 * Texts measure asynchronously in the plugin API (penpot-gotchas.md gotcha 2): right after the build call every
 * text reports 1×1, so the build laid the boards out from estimates. Run this file as ONE execute_code call per
 * pass, after the build call has settled:
 *   PASS = "measure"  — re-sets `characters` on every unmeasured text (height ≤ 1) this ticket's build created,
 *                       which forces the measurement; returns how many are still unmeasured (run again if > 0).
 *   PASS = "restack"  — inside each block re-flows the stacked texts by their measured heights, resizes the
 *                       block background, re-stacks the blocks of each stack, and resizes the board to fit;
 *                       returns `moved` (run again until 0).
 *                       r2 (#361): first lays out the follow rows (auto-width entry names, chips, the synonym mark) at measured widths.
 * Single writer, file-id guard, ONLY guard, page re-check, synchronous after that. Touches only shapes tagged by the build.
 * ONLY (as E29-D02's helper): the runner sets [n], one board per call, as for the build; left at "SET-ME", or
 * anything but one board number found on the page, it aborts before any write, so a forgotten ONLY never measures and
 * restacks all 12 boards in one bridge call. A board built in PARTS is relaid out once, after its last part.
 * Never retry after a "tab suspended" answer; probe read-only first.
 */
"use strict";
const WRITER = "SET-ME"; // storage.hpe1inst stamp of the writer instance (probe.js)
const PASS = "measure"; // "measure" first, then "restack"
const ONLY = "SET-ME"; // the runner sets [n]: one board per call; anything but one board number found on the page aborts
const FILE_ID = "SET-ME"; // the self-hosted CandleViewer file id, pasted locally before the run; never committed or posted
const PAGE_ID = null; // null = find the page by PAGE_NAME (must be unique); else pinned by id
const PAGE_NAME = "E12-D05 SCR-031 General";
const TICKET = "E12-D05";
const TAG = "cv:e12-d05";

if (typeof storage === "undefined" || storage.hpe1inst !== WRITER) return { skip: typeof storage === "undefined" ? null : storage.hpe1inst, note: "not the writer instance" };
if (!penpot.currentFile || penpot.currentFile.id !== FILE_ID) return { abort: "file", current: penpot.currentFile ? { name: penpot.currentFile.name } : null }; // the name only: an abort result is pasted into logs, so it never echoes a file id
if (!Array.isArray(ONLY) || ONLY.length !== 1 || !Number.isInteger(ONLY[0]) || ONLY[0] < 1) return { abort: "only", note: "ONLY must be [n], one board number (one board per call); nothing was touched" };
const pages = penpot.currentFile.pages || [];
let page = PAGE_ID ? pages.find((p) => p.id === PAGE_ID) || null : null;
// Duplicate same-name pages exist in the shared file (one empty, one an abandoned partial build): pick the page that holds only our
// ticket-prefixed frames, preferring the one that already has some; never a page with foreign content; abort when none is clean.
const normName = (s) => String(s || "").replace(/\s*\/\s*/g, "/");
if (!page) {
  const named = pages.filter((p) => p.name === PAGE_NAME).map((p) => { const c = { p, ours: 0, foreign: 0, unknown: false }; try { for (const s of (p.root && p.root.children) || []) { if (normName(s.name).startsWith(TICKET + "/")) c.ours++; else c.foreign++; } } catch (e) { c.unknown = true; } return c; });
  const clean = named.filter((c) => !c.unknown && c.foreign === 0).sort((a, b) => b.ours - a.ours);
  if (!named.length) return { abort: "page-not-found", pageName: PAGE_NAME };
  if (!clean.length) return { abort: "all-candidate-pages-hold-foreign-content", pages: named.map((c) => ({ id: c.p.id, ours: c.ours, foreign: c.foreign, unknown: c.unknown })) };
  page = clean[0].p;
}
// the one board must be on the page (read-only check, before any page switch or write)
const onPage = (() => { try { return (page.root.children || []).some((s) => { if (s.getPluginData(TAG) !== "v1") return false; const m = JSON.parse(s.getPluginData(TAG + ":meta") || "{}"); return m.role === "board" && m.board === ONLY[0]; }); } catch (e) { return false; } })();
if (!onPage) return { abort: "only", note: "board " + ONLY[0] + " of this ticket is not on the page; nothing was touched" };
if (!penpot.currentPage || penpot.currentPage.id !== page.id) { try { const r = penpot.openPage(page); if (r && typeof r.then === "function") await r; } catch (e) { /* re-check below */ } }
if (!penpot.currentPage || penpot.currentPage.id !== page.id) return { retry: true, pageId: page.id, note: "page not current yet — run again" };
// ---- synchronous from here ----
const warnings = [];
const meta = (s) => { try { if (s.getPluginData(TAG) !== "v1") return null; return JSON.parse(s.getPluginData(TAG + ":meta") || "{}"); } catch (e) { return null; } };
const boards = (page.root.children || []).filter((s) => { const m = meta(s); return m && m.role === "board" && m.board === ONLY[0]; });
const result = { pass: PASS, boards: boards.length, measured: 0, unmeasured: 0, moved: 0, resized: 0, warnings };

if (PASS === "measure") {
  result.slTall = []; // r4 (the r3 script check): a single-line text (meta sl) measured taller than one line, i.e. its width estimate was short and it wrapped; read it in the export
  const walk = (s) => {
    for (const c of s.children || []) {
      const m = meta(c);
      if (m && m.role === "text" && c.type === "text") {
        if (c.height <= 1) {
          try { const txt = c.characters; c.characters = txt + " "; c.characters = txt; result.measured++; } catch (e) { warnings.push("measure: " + (e && e.message || e)); }
          result.unmeasured++;
        } else if (m.sl) {
          const fs = Number(c.fontSize) || 0, lh = Number(c.lineHeight) || 1.2;
          if (fs && c.height > fs * lh * 1.5) result.slTall.push({ text: String(c.characters).slice(0, 40), h: Math.round(c.height), line: Math.round(fs * lh) });
        }
      }
      if (c.children && c.children.length) walk(c);
    }
  };
  for (const b of boards) walk(b);
  result.note = (result.unmeasured ? "texts were still unmeasured and have been poked; run PASS=\"measure\" again until unmeasured is 0, then PASS=\"restack\"" : "all texts measured; run PASS=\"restack\"") + (result.slTall.length ? "; " + result.slTall.length + " single-line text(s) measured taller than one line (slTall): check them in the export" : "");
  return result;
}

if (PASS === "restack") {
  for (const b of boards) {
    const kids = (b.children || []).slice();
    const blocks = new Map(); // blk -> { shapes: [], bg, stk, idx }
    for (const c of kids) {
      const m = meta(c);
      if (!m || !m.blk) continue;
      let blk = blocks.get(m.blk);
      if (!blk) { blk = { shapes: [], bg: null, stk: m.stk, idx: m.idx == null ? 0 : m.idx, pad: 14, gap: 12, texts: [] }; blocks.set(m.blk, blk); }
      blk.shapes.push(c);
      if (m.bg) { blk.bg = c; if (m.pad != null) blk.pad = m.pad; if (m.gap != null) blk.gap = m.gap; }
      if (m.role === "text" && m.after != null) blk.texts.push({ s: c, after: m.after });
    }
    // 0. follow rows (#361 r2): the shapes tagged fr (row) / fo (group) / fg (the gap before the group) are laid out left to right
    // at their MEASURED widths: an fbg rect is resized to its group's flab label's right + fp, then each group after the first is
    // moved to the previous group's right + its fg (the token gap after an auto-width entry name, the chips' space.1 padding, the
    // synonym mark's underline at the word's width). Boards without such tags are untouched.
    const frows = new Map();
    const walkF = (s) => { for (const c of s.children || []) { const m = meta(c); if (m && m.fr != null && m.fo != null) { let r = frows.get(m.fr); if (!r) { r = new Map(); frows.set(m.fr, r); } let g = r.get(m.fo); if (!g) { g = { items: [], gap: Number(m.fg) || 0 }; r.set(m.fo, g); } g.items.push({ s: c, m }); } if (c.children && c.children.length) walkF(c); } };
    walkF(b);
    for (const r of frows.values()) {
      let right = null;
      for (const fo of Array.from(r.keys()).sort((p, q) => p - q)) {
        const g = r.get(fo), lab = g.items.find((it) => it.m.flab);
        if (right !== null) {
          const dx = right + g.gap - Math.min.apply(null, g.items.map((it) => it.s.x));
          if (Math.abs(dx) > 0.5) { for (const it of g.items) it.s.x = it.s.x + dx; result.moved++; }
        }
        for (const it of g.items) {
          if (!it.m.fbg || !lab) continue;
          const want = lab.s.x + Math.max(1, lab.s.width) + (Number(it.m.fp) || 0) - it.s.x;
          if (want > 0 && Math.abs(want - it.s.width) > 0.5) { try { it.s.resize(want, it.s.height); result.resized++; } catch (e) { warnings.push("follow resize: " + (e && e.message || e)); } }
        }
        right = Math.max.apply(null, g.items.map((it) => it.s.x + Math.max(1, it.s.width)));
      }
    }
    // 1. inner re-flow of stacked texts (cards): keep the first text's y, stack the rest by measured height
    for (const blk of blocks.values()) {
      if (blk.texts.length < 2) continue;
      blk.texts.sort((a, b2) => a.s.y - b2.s.y);
      let cy = blk.texts[0].s.y;
      for (const t of blk.texts) {
        if (Math.abs(t.s.y - cy) > 0.5) { t.s.y = cy; result.moved++; }
        cy += Math.max(1, t.s.height) + t.after;
      }
    }
    // 2. background height = content bottom + pad (fixed frames, pad 0, keep their height)
    for (const blk of blocks.values()) {
      if (!blk.bg) continue;
      const top = blk.bg.y;
      let bottom = top;
      for (const s of blk.shapes) { if (s === blk.bg) continue; bottom = Math.max(bottom, s.y + Math.max(1, s.height)); }
      const wanted = blk.pad === 0 ? blk.bg.height : Math.max(24, bottom - top + blk.pad);
      if (Math.abs(wanted - blk.bg.height) > 0.5) { try { blk.bg.resize(blk.bg.width, wanted); result.resized++; } catch (e) { warnings.push("resize: " + (e && e.message || e)); } }
    }
    // 3. re-stack blocks within each stack by idx (then by y), keeping the first block's top
    const stacks = new Map();
    for (const blk of blocks.values()) { if (!blk.stk) continue; let st = stacks.get(blk.stk); if (!st) { st = []; stacks.set(blk.stk, st); } st.push(blk); }
    const blockTop = (blk) => Math.min.apply(null, blk.shapes.map((s) => s.y));
    const blockBottom = (blk) => Math.max.apply(null, blk.shapes.map((s) => s.y + Math.max(1, s.height)));
    for (const st of stacks.values()) {
      if (st.length < 2) continue;
      st.sort((a, b2) => (a.idx - b2.idx) || (blockTop(a) - blockTop(b2)));
      let cursor = blockTop(st[0]);
      for (const blk of st) {
        const top = blockTop(blk);
        const dy = cursor - top;
        if (Math.abs(dy) > 0.5) { for (const s of blk.shapes) s.y = s.y + dy; result.moved++; }
        cursor = blockBottom(blk) + (blk.gap == null ? 12 : blk.gap);
      }
    }
    // 4. board height to fit
    let maxBottom = b.y;
    for (const c of b.children || []) maxBottom = Math.max(maxBottom, c.y + Math.max(1, c.height));
    const wantedH = maxBottom - b.y + 32;
    if (Math.abs(wantedH - b.height) > 0.5) { try { b.resize(b.width, wantedH); result.resized++; } catch (e) { warnings.push("board resize: " + (e && e.message || e)); } }
  }
  result.note = result.moved ? "run PASS=\"restack\" again until moved is 0" : "layout converged; run the dedupe script, then probe until every instance agrees, then export";
  return result;
}
return { abort: "unknown PASS", PASS };
