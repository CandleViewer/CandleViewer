const root = penpot.currentPage.root.children.find((s) => s.name === "__NAME__");
if (!root) return { err: "no root" };
const r = storage.cvsheet.lint(root);
return { counts: r.counts, shapes: r.shapes, findings: r.findings.filter((f) => f.kind !== "overlap").map((f) => ({ k: f.kind, p: f.path.slice(-140), d: f.detail.slice(0, 120) })) };
