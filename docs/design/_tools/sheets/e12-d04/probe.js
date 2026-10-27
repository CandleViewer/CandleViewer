/* probe.js — READ-ONLY probe for the Penpot MCP bridge (shared-plugin convention).
 *
 * Several plugin instances may be connected and every execute_code call is broadcast to all of them, so this
 * probe (a) stamps each instance once with a random `storage.hpe1inst` id and (b) reports what that instance sees.
 * Run it repeatedly (it mutates nothing in the file) until the answers are stable, then choose ONE stamp as the
 * WRITER constant of every write script. Also run it after any "tab suspended / no heartbeat" answer: a suspended
 * call stays queued and runs when the tab wakes, so a retry would duplicate the write — probe first, decide after.
 */
"use strict";
const norm = (s) => String(s || "").replace(/\s*\/\s*/g, "/");
if (typeof storage === "undefined") return { error: "no storage object on this bridge" };
if (!storage.hpe1inst) storage.hpe1inst = "i-" + Math.random().toString(36).slice(2, 10) + "-" + Date.now().toString(36);
const file = penpot.currentFile ? { id: penpot.currentFile.id, name: penpot.currentFile.name } : null;
const page = penpot.currentPage ? { id: penpot.currentPage.id, name: penpot.currentPage.name } : null;
const pages = penpot.currentFile ? (penpot.currentFile.pages || []).map((p) => ({ id: p.id, name: p.name })) : [];
// top-level frames on the current page that belong to our design tickets, with their version stamps
const ours = [];
if (penpot.currentPage && penpot.currentPage.root) {
  for (const s of penpot.currentPage.root.children || []) {
    const nm = norm(s.name);
    if (/^E\d{2}-D\d{2}\//.test(nm)) { // any design ticket's ticket-prefixed frames (E11-D03 etc.)
      let kids = 0;
      const walk = (x) => { for (const c of x.children || []) { kids++; walk(c); } };
      try { walk(s); } catch (e) { /* leaf */ }
      let ver = null;
      try { ver = s.getPluginData("hpe1ver") || null; } catch (e) { /* no plugin data */ }
      ours.push({ name: s.name, id: s.id, type: s.type, hpe1ver: ver, descendants: kids, x: s.x, y: s.y, w: s.width, h: s.height });
    }
  }
}
return { inst: storage.hpe1inst, file, page, pages, ours, now: new Date().toISOString() };
