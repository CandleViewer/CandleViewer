/* listexp.js — READ-ONLY: this ticket's top-level boards on its page (by plugin-data TAG), with board number, theme,
 * id, name, hpe1ver, exportAs (meta), descendant count and size. Reads page.root directly; never switches pages. */
"use strict";
const TAG = "SET-ME";
const PAGE_ID = "SET-ME";
if (!penpot.currentFile) return { abort: "no file" };
const page = (penpot.currentFile.pages || []).find((p) => p.id === PAGE_ID);
if (!page) return { abort: "page-not-found" };
const out = [];
for (const s of (page.root && page.root.children) || []) {
  let m = null;
  try { if (s.getPluginData(TAG) !== "v1") continue; m = JSON.parse(s.getPluginData(TAG + ":meta") || "{}"); } catch (e) { continue; }
  if (!m || m.role !== "board") continue;
  let ver = null; try { ver = s.getPluginData("hpe1ver") || null; } catch (e) { /* none */ }
  let kids = 0; const walk = (x) => { for (const c of x.children || []) { kids++; walk(c); } }; try { walk(s); } catch (e) { /* leaf */ }
  out.push({ board: m.board, theme: m.theme || null, id: s.id, name: s.name, ver, exportAs: m.exportAs || null, kids, w: s.width, h: s.height });
}
return { page: page.name, current: penpot.currentPage ? penpot.currentPage.id === page.id : false, boards: out };
