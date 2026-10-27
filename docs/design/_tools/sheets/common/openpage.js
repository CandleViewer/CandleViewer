/* openpage.js — open (make current) the page PAGE_ID in this tab only; returns the current page after the switch. */
const PAGE_ID = "SET-ME";
const page = (penpot.currentFile.pages || []).find((p) => p.id === PAGE_ID);
if (!page) return { abort: "page-not-found" };
if (!penpot.currentPage || penpot.currentPage.id !== page.id) penpot.openPage(page);
return { current: penpot.currentPage ? penpot.currentPage.name : null, wanted: page.name };
