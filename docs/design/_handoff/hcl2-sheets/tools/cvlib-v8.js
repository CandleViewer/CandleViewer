// cvlib v8 — E05-D02 (#161) Penpot build helpers (v8: file and page ids resolved by name at install, for the self-hosted Penpot move). Paste as the prologue of an execute_code call:
//   <contents of this file>
//   const cv = storage.cvd02; ...
// Every shape it creates is tagged with shared plugin data cvd02/kind so D02's own shapes can be found
// (and only those touched) on a rebuild. Tokens are looked up by exact name; a missing token throws.
if (!storage.cvd02inst) storage.cvd02inst = "ifidz07x7";
if (!storage.cvd02 || storage.cvd02.v < 8) {
  const cv = { v: 8 };
  const RAD = ["borderRadiusTopLeft", "borderRadiusTopRight", "borderRadiusBottomRight", "borderRadiusBottomLeft"];
  cv.RAD = RAD;
  cv.T = (name) => {
    const t = penpotUtils.findTokenByName(name);
    if (!t) throw new Error("token not found: " + name);
    return t;
  };
  cv.tag = (s, kind) => { try { s.setSharedPluginData("cvd02", "kind", kind || "part"); } catch (e) { /* groups etc. */ } return s; };
  cv.bind = (s, name, props) => { s.applyToken(cv.T(name), props); return s; };
  cv.solidStroke = (alignment) => ({ strokeColor: "#000000", strokeOpacity: 1, strokeStyle: "solid", strokeWidth: 1, strokeAlignment: alignment || "inner" });
  // A board, optionally with flex layout and token bindings.
  // o: { dir, align, justify, hs, vs, wrap, fill, stroke, strokeWidth, strokeAlign, radius, pad, padX, padY,
  //      padT, padR, padB, padL, gap, rowGap, colGap, height, width, minW, minH, opacity, shadow, kind, clip }
  cv.board = (name, o = {}) => {
    const b = penpot.createBoard();
    b.name = name;
    cv.tag(b, o.kind || "part");
    b.fills = [];
    if (o.clip === false) b.clipContent = false;
    if (o.dir) {
      const f = b.addFlexLayout();
      f.dir = o.dir;
      f.alignItems = o.align || "center";
      f.justifyContent = o.justify || "start";
      f.horizontalSizing = o.hs || "auto";
      f.verticalSizing = o.vs || "auto";
      if (o.wrap) f.wrap = o.wrap;
      f.rowGap = 0; f.columnGap = 0;
      f.topPadding = 0; f.rightPadding = 0; f.bottomPadding = 0; f.leftPadding = 0;
    }
    if (o.fill) cv.bind(b, o.fill, ["fill"]);
    if (o.stroke) {
      b.strokes = [cv.solidStroke(o.strokeAlign)];
      cv.bind(b, o.stroke, ["strokeColor"]);
      if (o.strokeWidth) cv.bind(b, o.strokeWidth, ["strokeWidth"]);
    }
    if (o.radius) cv.bind(b, o.radius, RAD);
    if (o.pad) cv.bind(b, o.pad, ["paddingLeft", "paddingRight", "paddingTop", "paddingBottom"]);
    if (o.padX) cv.bind(b, o.padX, ["paddingLeft", "paddingRight"]);
    if (o.padY) cv.bind(b, o.padY, ["paddingTop", "paddingBottom"]);
    if (o.padT) cv.bind(b, o.padT, ["paddingTop"]);
    if (o.padR) cv.bind(b, o.padR, ["paddingRight"]);
    if (o.padB) cv.bind(b, o.padB, ["paddingBottom"]);
    if (o.padL) cv.bind(b, o.padL, ["paddingLeft"]);
    if (o.gap) cv.bind(b, o.gap, ["columnGap", "rowGap"]);
    if (o.rowGap) cv.bind(b, o.rowGap, ["rowGap"]);
    if (o.colGap) cv.bind(b, o.colGap, ["columnGap"]);
    if (o.height) { if (b.flex) b.flex.verticalSizing = "fix"; cv.bind(b, o.height, ["height"]); }
    if (o.width) { if (b.flex) b.flex.horizontalSizing = "fix"; cv.bind(b, o.width, ["width"]); }
    if (o.minW) cv.bind(b, o.minW, ["layoutItemMinW"]);
    if (o.minH) cv.bind(b, o.minH, ["layoutItemMinH"]);
    if (o.opacity) cv.bind(b, o.opacity, ["opacity"]);
    if (o.shadow) cv.bind(b, o.shadow, ["shadow"]);
    return b;
  };
  // A text node bound to a typography token and a colour token.
  cv.text = (chars, typo, color, o = {}) => {
    const t = penpot.createText(chars);
    if (!t) throw new Error("createText failed for " + chars);
    cv.tag(t, "text");
    t.name = o.name || "label";
    cv.bind(t, typo, ["typography"]);
    cv.bind(t, color, ["fill"]);
    t.growType = o.grow || "auto-width";
    if (o.align) t.align = o.align;
    if (o.decoration) t.textDecoration = o.decoration;
    return t;
  };
  cv.rect = (name, o = {}) => {
    const r = penpot.createRectangle();
    r.name = name; cv.tag(r, "part");
    r.fills = [];
    if (o.fill) cv.bind(r, o.fill, ["fill"]);
    if (o.stroke) { r.strokes = [cv.solidStroke(o.strokeAlign)]; cv.bind(r, o.stroke, ["strokeColor"]); if (o.strokeWidth) cv.bind(r, o.strokeWidth, ["strokeWidth"]); }
    if (o.radius) cv.bind(r, o.radius, RAD);
    if (o.w && o.h) r.resize(o.w, o.h);
    if (o.width) cv.bind(r, o.width, ["width"]);
    if (o.height) cv.bind(r, o.height, ["height"]);
    if (o.opacity) cv.bind(r, o.opacity, ["opacity"]);
    return r;
  };
  cv.ellipse = (name, o = {}) => {
    const e = penpot.createEllipse();
    e.name = name; cv.tag(e, "part");
    e.fills = [];
    if (o.fill) cv.bind(e, o.fill, ["fill"]);
    if (o.stroke) { e.strokes = [cv.solidStroke(o.strokeAlign)]; cv.bind(e, o.stroke, ["strokeColor"]); if (o.strokeWidth) cv.bind(e, o.strokeWidth, ["strokeWidth"]); }
    if (o.w && o.h) e.resize(o.w, o.h);
    if (o.width) cv.bind(e, o.width, ["width"]);
    if (o.height) cv.bind(e, o.height, ["height"]);
    return e;
  };
  cv.add = (parent, ...kids) => { for (const k of kids) if (k) parent.appendChild(k); return parent; };
  // Library component lookup by exact name (or path/name).
  cv.comp = (name) => {
    const c = penpot.library.local.components.find((x) => x.name === name || (x.path ? x.path + " / " + x.name : x.name) === name);
    if (!c) throw new Error("component not found: " + name);
    return c;
  };
  // Recolour every vector stroke under a shape to a colour token (icons are stroke-drawn, fill none).
  cv.strokeTo = (root, tokenName) => {
    const tok = cv.T(tokenName);
    const hits = penpotUtils.findShapes((s) => (s.type === "path" || s.type === "rectangle" || s.type === "ellipse" || s.type === "bool") && s.strokes && s.strokes.length > 0, root);
    for (const s of hits) s.applyToken(tok, ["strokeColor"]);
    return hits.length;
  };
  // An icon instance from the icon/{name} library component, sized by a sizing token, stroke bound.
  cv.icon = (name, colorToken, sizeToken) => {
    const inst = cv.iconComp(name).instance();
    inst.name = "icon-" + name;
    if (sizeToken) cv.bind(inst, sizeToken, ["width", "height"]);
    if (colorToken) cv.strokeTo(inst, colorToken);
    return inst;
  };
  // Turn built boards into main components and group them as one variant set.
  // items: [{ shape: Board, props: { Variant: "primary", State: "default" } }]
  cv.variants = (setName, items) => {
    const mains = [];
    for (const it of items) {
      const comp = penpot.library.local.createComponent([it.shape]);
      comp.name = setName;
      mains.push({ shape: comp.mainInstance(), properties: it.props });
    }
    const vc = penpotUtils.createVariantContainer(mains);
    vc.name = setName;
    cv.tag(vc, "variant-set");
    return vc;
  };
  // Find D02-created shapes (tagged) on a page.
  cv.mine = (root, kind) => penpotUtils.findShapes((s) => { try { const k = s.getSharedPluginData("cvd02", "kind"); return k && (!kind || k === kind); } catch (e) { return false; } }, root);
  cv.page = (name) => { const p = penpotUtils.getPageByName(name); if (!p) throw new Error("page not found: " + name); return p; };
  // Text measurement is asynchronous (a new text reads 1x1 until the renderer measures it), and flex parents do not
  // re-layout after it. Post-process in LATER calls: cv.touchTexts(root) once, then cv.relayout(root).
  cv.touchTexts = (root) => {
    const ts = penpotUtils.findShapes((s) => s.type === "text" && s.height <= 1, root);
    for (const t of ts) { const ch = t.characters; t.characters = ch + " "; t.characters = ch; }
    return ts.length;
  };
  cv.depth = (s) => { let d = 0; let p = s.parent; while (p) { d++; p = p.parent; } return d; };
  // v7: relayout touches only the documentation structure, never a shape inside a component main or copy:
  // toggling sizing on a main re-syncs every copy of it in the file (CMP-001 is instanced everywhere), which
  // froze the Penpot page for many minutes on 2026-10-20. Use cv.relayoutMains(set) only when a main truly needs it.
  const inComp = (s) => { try { return s.isComponentMainInstance() || s.isComponentInstance(); } catch (e) { return false; } };
  cv.relayoutMains = (root) => {
    const bs = penpotUtils.findShapes((s) => s.type === "board" && !!s.flex, root);
    if (root.type === "board" && root.flex) bs.push(root);
    bs.sort((a, b) => cv.depth(b) - cv.depth(a));
    for (const b of bs) { const h = b.flex.horizontalSizing, v = b.flex.verticalSizing; b.flex.horizontalSizing = "fix"; b.flex.horizontalSizing = h; b.flex.verticalSizing = "fix"; b.flex.verticalSizing = v; }
    return bs.length;
  };
  cv.relayout = (root) => {
    const bs = penpotUtils.findShapes((s) => s.type === "board" && !!s.flex && !inComp(s), root);
    if (root.type === "board" && root.flex && !inComp(root)) bs.push(root);
    bs.sort((a, b) => cv.depth(b) - cv.depth(a));
    for (const b of bs) { const h = b.flex.horizontalSizing, v = b.flex.verticalSizing; b.flex.horizontalSizing = "fix"; b.flex.horizontalSizing = h; b.flex.verticalSizing = "fix"; b.flex.verticalSizing = v; }
    return bs.length;
  };
  cv.unmeasured = (root) => penpotUtils.findShapes((s) => s.type === "text" && s.height <= 1, root).length;
  // Board/component names containing "/" are normalised by Penpot to "a / b"; icon components have path "icon".
  cv.iconComp = (name) => { const c = penpot.library.local.components.find((x) => x.path === "icon" && x.name === name); if (!c) throw new Error("icon not found: " + name); return c; };
  cv.sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  // [PENPOT-SHARED] convention (RelayRoom thread 01a157dd…): one plugin instance serves every agent, so each
  // call checks the file, opens its own page, re-checks it after the await, then does ONLY synchronous work.
  // v8: the file is the one this instance has open (one Penpot user per lane), and page ids are looked up by name.
  cv.FILE = penpot.currentFile ? penpot.currentFile.id : null;
  const pg = (n) => { const p = penpotUtils.getPageByName(n); return p ? p.id : null; };
  cv.PAGES = { atoms: pg("10 Components — Atoms"), molecules: pg("11 Components — Molecules"), tokens02: pg("02 Tokens — Semantic (Dark)") };
  // Usage: const bad = await cv.enter(cv.PAGES.atoms); if (bad) return bad;  ...then synchronous work only.
  // BROADCAST: the bridge sends every call to EVERY connected plugin instance (two tabs => everything runs twice,
  // and a suspended tab may run a queued call minutes later). Only the designated writer instance mutates:
  // storage.cvd02inst is a per-instance random id; cv.WRITER is the chosen writer's id (set by a broadcast
  // handshake call). Non-writers wait 20 s and answer {skip}, so the caller usually receives the writer's answer.
  cv.enter = async (pageId) => {
    if (!storage.cvd02inst) storage.cvd02inst = "ifidz07x7"; // v8.1: self-hosted, one instance per user, so it self-claims
    if (!cv.WRITER) return { needWriter: true, inst: storage.cvd02inst };
    if (storage.cvd02inst !== cv.WRITER) { await new Promise((r) => setTimeout(r, 20000)); return { skip: "not-writer", inst: storage.cvd02inst }; }
    if (!penpot.currentFile || penpot.currentFile.id !== cv.FILE) return { abort: "file", file: penpot.currentFile ? penpot.currentFile.id : null };
    await penpot.openPage(pageId);
    if (!penpot.currentPage || penpot.currentPage.id !== pageId) return { retry: "page", page: penpot.currentPage ? penpot.currentPage.id : null };
    return null;
  };
  // v6: the writer is PINNED. Between 13:30Z and 14:43Z on 2026-10-20, agents re-running the old WRITER handshake
  // left the two tabs disagreeing (split brain: both mutated, duplicate sections). Nobody may change WRITER at run
  // time; to move the writer, ship a new cvlib version with a new pinned id.
  Object.defineProperty(cv, "WRITER", { value: "ifidz07x7", writable: false, enumerable: true, configurable: false });
  storage.cvd02 = cv;
}
