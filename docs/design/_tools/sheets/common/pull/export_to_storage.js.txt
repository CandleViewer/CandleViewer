const SHAPE_ID = "SET-ME";
const s = penpot.currentPage.getShapeById(SHAPE_ID);
if (!s) return { err: "shape not on the current page" };
const t0 = Date.now();
const r = await Promise.race([s.export({ type: "png", scale: 1 }), new Promise((res) => setTimeout(() => res("TIMEOUT"), 100000))]);
if (r === "TIMEOUT") return { err: "TIMEOUT", ms: Date.now() - t0 };
storage.pngbuf = r;
storage.pngname = s.name;
return { name: s.name, w: Math.round(s.width), h: Math.round(s.height), bytes: r.length, ms: Date.now() - t0 };
