// cvsheet v4.2 — render JSON "board sheets" with cvlib v8 (v4.2: one-sided paddings drawn, see below). v4 = v3.1
// (cvsheet-v1.js, 2026-10-22 20:17Z: padSides, S.put index by id) + section styles, clone nodes, a token-lookup cache
// and a read-only lint. v4.1 (review of v4): clone nodes are resolved in JSON (Penpot applies token binds
// asynchronously, so shape.clone() of a shape made in the same call copies it without its binds), the token cache
// lives for one S.root / S.section run, and the lint gains the `unbound` kind and a wider overlap check. The v3.1 API
// and node schema are unchanged, so v3 callers keep working.
// Install cvlib v8 first (storage.cvd02), then paste this whole file as the prologue of an execute_code call and use
// storage.cvsheet:
//   const cv = storage.cvd02, sh = storage.cvsheet;
//   const bad = await cv.enter(PAGE_ID); if (bad) return bad;          // then synchronous work only
//   const root = sh.root("E08-D07 / 01 SCR-100/populated", { w: 1184, h: 456, x: 0, y: 0, o: {...} });  // find-or-create
//   sh.section(root, SECTION); // SECTION = { into: "" | "screen" | "screen/grid", node, styles? }: replaces the child of
//                              // that parent with the same name (same index) and renders the node tree
//   return sh.report(root);  // counts + every problem found
// One section per call. Text measurement and token binds are asynchronous: in a LATER call run cv.touchTexts(root) and
// cv.relayout(root), then (read-only) sh.lint(root).
//
// Node schema. Token names are exact Penpot token names; raw px only in w, h, x, y. Unknown keys throw.
//   board : { t:"board", name, o:{cv.board options}, w, h, x, y, abs, hs, vs, alignSelf, kids:[...] }
//   text  : { t:"text", name, chars, typo, color, w (wrap width: fixed width, auto-height), align, x, y, abs, hs, vs }
//   rect  : { t:"rect", name, o:{fill, stroke, strokeWidth, strokeAlign, radius, opacity, width, height}, w, h, x, y, abs, hs, vs }
//   ellipse: same keys as rect
//   icon  : { t:"icon", name, icon, color, size, x, y, abs }
//   inst  : { t:"inst", name, set, props:{Prop:"value"}, texts:{childName:"chars"}, hide:[childName], show:[childName],
//             w, h, x, y, abs, hs, vs }
//   clone : { t:"clone", name, of, set:{ "<path>": { chars, color } }, texts:{ "<instLayer>": chars }, x, y, abs }  (v4)
// x/y are relative to the parent. In a flex parent a positioned node needs abs:true (it leaves the flow).
//
// v4 additions:
//   styles: a section may carry styles: { key: partialNode }; any node may carry "s": key. Before validation the node is
//           expanded to Object.assign({}, styles[key], node) without "s" (node keys win), recursively over kids. An
//           unknown style key throws.
//   clone : stands for a copy of the EARLIER sibling named `of` (exactly one earlier sibling may carry that name). v4.1
//           builds the copy in JSON before anything is drawn (S.resolve, the mirror of compact.py materialize()): a deep
//           copy of that sibling's node (its own clones already resolved), renamed; each `set` path (child names joined
//           by "/", relative to the copy, every segment unique among its siblings; "" = the copy itself; the target must
//           be a text) takes the given chars and/or color; each `texts` key (a key of the copied inst's own `texts`)
//           takes the given chars; x, y and abs, when given, replace the source's. The copy is then drawn like any
//           node, with its own token binds. No shape.clone() is used. A clone directly at a section root throws and
//           removes nothing (its source was drawn by an earlier call, so there is no JSON to copy).
//   cache : while S.root or S.section runs, storage.cvd02.T is memoised by token name (a miss is never cached); cvlib's
//           own T is put back when the run ends (v4.1; v4 kept a memo for the whole plugin session, removed at install).
//           S.memo(fn) runs fn the same way.
//   lint  : S.lint(root) is read-only: { counts, findings (at most 40 of {kind, path, detail}), shapes }.
//
// v4.2 (2026-10-24, E08-D07 PNG review): one-sided paddings. Penpot draws a flex layout's padding through its padding
// type: "simple" (the type a new flex layout gets) draws [top, right, top, right]; only "multiple" draws the four
// sides. cvlib's cv.board binds a token per side (padL, padR, padT, padB, padX, padY, pad) and never sets the type, so
// a padL alone draws 0 on the left (and a padR alone draws on both sides, a padT alone on top and bottom). v3.1's
// padSides re-assigned the four sides through the plugin setters, which switches the type (live test 2026-10-22,
// "after the bind"), but it runs in finish(), in the SAME call as the binds, and Penpot applies token binds
// asynchronously (the same live tests: a bind lands about 400 ms later): it read and wrote the pre-bind values (cvlib
// zeroes the four sides) and the type stayed simple, so every one-sided padding drawn by v3.1 to v4.1 is lost (E08-D07
// boards 01-04, 07, 08, 10, 11, 26; E32-D02 board 13's legs). v4.2 re-assigns the sides in a LATER call, once the binds
// have landed: S.pads(root) walks the flex boards under root (never inside a component copy or main), and every board
// whose bound padding tokens do not fit the simple pattern (top != bottom or left != right) and whose bound sides
// already hold their tokens' values gets its four sides re-assigned with their current values (the live-tested
// recipe), once per plugin session and value set. S.report(root) runs S.pads(root) first, so the existing call order
// applies it with no new step: every section call's report fixes the boards of the EARLIER section calls, and the
// touch step's report (a later call than the last section) fixes the last section's boards, before relayout. The
// report gains padsFixed and padsPending (bound sides whose values have not landed yet: a later report retries them).
// S.lint stays read-only. The v4.1 API, node schema and output are otherwise unchanged.
// Install: mkcall4.py prints cvsheet-v4.js (v4.1) for its `install` step and its GUARD asks for v >= 4.1, so v4.2 is
// installed by running this file once per plugin session BEFORE the renders (each file's guard only installs over a
// lower version: a later v4.1 install is a no-op). A tab reload empties storage, after which mkcall4 would install
// v4.1 again: re-run this file after every reload.
if (!storage.cvsheet || storage.cvsheet.v < 4.2) {
  const S = { v: 4.2 };
  const KEYS = {
    board: ["t", "name", "o", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "kids", "note"],
    text: ["t", "name", "chars", "typo", "color", "w", "align", "x", "y", "abs", "hs", "vs", "alignSelf", "note"],
    rect: ["t", "name", "o", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "note"],
    ellipse: ["t", "name", "o", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "note"],
    icon: ["t", "name", "icon", "color", "size", "x", "y", "abs", "alignSelf", "note"],
    inst: ["t", "name", "set", "props", "texts", "hide", "show", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "note"],
    clone: ["t", "name", "of", "set", "texts", "x", "y", "abs", "note"],
  };
  const SET_KEYS = ["chars", "color"];
  const own = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
  const isObj = (o) => !!o && typeof o === "object" && !Array.isArray(o);
  // v4.1: v4 wrapped cvlib's T for the whole plugin session (the original kept as T0): put the original back
  const unwrapT = (cv) => { if (cv && cv.T0) { cv.T = cv.T0; delete cv.T0; delete cv.Tmemo; } };
  const cvl = () => {
    const cv = storage.cvd02;
    if (!cv || cv.v < 8) throw new Error("cvlib v8 not installed");
    unwrapT(cv);
    return cv;
  };
  unwrapT(storage.cvd02);
  // v4.1: memoise token lookups by name while fn runs, then put cvlib's own T back (also when fn throws). T throws on a
  // miss, so a miss is never cached. A nested run uses the outer run's memo.
  S.memo = (fn) => {
    const cv = cvl();
    if (cv.Tmemo) return fn();
    const T0 = cv.T;
    const memo = new Map();
    cv.Tmemo = memo;
    cv.T = (name) => {
      const hit = memo.get(name);
      if (hit) return hit;
      const t = T0(name);
      if (t) memo.set(name, t);
      return t;
    };
    try { return fn(); } finally { cv.T = T0; delete cv.Tmemo; }
  };
  S.child = (parent, name) => (parent.children || []).find((c) => c.name === name) || null;
  S.comp = (set, props) => {
    const all = penpot.library.local.components;
    let c = null;
    if (props && Object.keys(props).length) {
      const hit = (vp) => !!vp && Object.keys(props).every((p) => vp[p] === props[p]);
      c = all.find((k) => {
        if (k.name !== set) return false;
        let vp = null;
        try { vp = k.isVariant && k.isVariant() ? k.variantProps : null; } catch (e) { vp = null; }
        return hit(vp);
      });
      // v3: library.local.components lists only the FIRST variant of each variant set; search the set's variants
      for (const k of c ? [] : all.filter((x) => x.name === set)) {
        let vcs = [];
        try { vcs = k.variants ? k.variants.variantComponents() : []; } catch (e) { vcs = []; }
        c = vcs.find((v) => { let vp = null; try { vp = v.variantProps; } catch (e) { vp = null; } return hit(vp); }) || null;
        if (c) break;
      }
    } else {
      c = all.find((k) => k.name === set || (k.path ? k.path + " / " + k.name : k.name) === set);
    }
    if (!c) throw new Error("component not found: " + set + " " + JSON.stringify(props || {}));
    return c;
  };
  const place = (s, n, parent) => {
    if (n.abs && parent.flex) s.layoutChild.absolute = true;
    if (n.x !== undefined || n.y !== undefined) {
      if (parent.flex && !n.abs) throw new Error("x/y without abs inside a flex parent: " + n.name);
      penpotUtils.setParentXY(s, n.x || 0, n.y || 0);
    }
    if (parent.flex && !n.abs) {
      if (n.hs) s.layoutChild.horizontalSizing = n.hs;
      if (n.vs) s.layoutChild.verticalSizing = n.vs;
      if (n.alignSelf) s.layoutChild.alignSelf = n.alignSelf;
    }
  };
  const make = (n) => {
    const cv = cvl();
    if (!n || !n.t || !KEYS[n.t]) throw new Error("bad node type: " + JSON.stringify(n && n.t));
    if (n.t === "clone") throw new Error("clone node not resolved: " + n.name + " (render through S.render, S.put or S.section)");
    for (const k of Object.keys(n)) if (KEYS[n.t].indexOf(k) < 0) throw new Error("unknown key '" + k + "' on " + n.t + " " + n.name);
    if (!n.name) throw new Error("node without a name (" + n.t + ")");
    if (n.t === "board") return cv.board(n.name, n.o || {});
    if (n.t === "text") return cv.text(String(n.chars), n.typo, n.color, { name: n.name, align: n.align });
    if (n.t === "rect") return cv.rect(n.name, Object.assign({}, n.o || {}, n.w && n.h ? { w: n.w, h: n.h } : {}));
    if (n.t === "ellipse") return cv.ellipse(n.name, Object.assign({}, n.o || {}, n.w && n.h ? { w: n.w, h: n.h } : {}));
    if (n.t === "icon") { const s = cv.icon(n.icon, n.color, n.size); s.name = n.name; return s; }
    const s = S.comp(n.set, n.props).instance();
    s.name = n.name;
    return s;
  };
  // v3.1: a padding token bound to some sides only does not draw while the layout's padding type is "simple"
  // (live test 2026-10-22: paddingLeft alone left the child at x 0). Re-assigning each side through the plugin setter
  // switches the layout to multiple sides and keeps the token binding. v4.2: kept as it was, but it has no effect here
  // (finish() runs in the same call as the binds, before they land); S.pads below does the re-assignment later.
  const padSides = (s, o) => {
    if (!s.flex || !o || !(o.pad || o.padX || o.padY || o.padT || o.padR || o.padB || o.padL)) return;
    const f = s.flex; const v = [f.topPadding, f.rightPadding, f.bottomPadding, f.leftPadding];
    f.topPadding = v[0]; f.rightPadding = v[1]; f.bottomPadding = v[2]; f.leftPadding = v[3];
  };
  S.padSides = padSides;
  const finish = (s, n) => {
    if (n.t === "board") padSides(s, n.o);
    if (n.t === "board" && (n.w || n.h)) {
      s.resize(n.w || s.width, n.h || s.height);
      // v2: a resize turns both flex sizings to "fix"; restore the hug on the axis the node did not size
      if (s.flex) {
        s.flex.horizontalSizing = n.w ? "fix" : ((n.o && n.o.hs) || "auto");
        s.flex.verticalSizing = n.h ? "fix" : ((n.o && n.o.vs) || "auto");
      }
    }
    if (n.t === "text" && n.w) { s.resize(n.w, Math.max(s.height, 16)); s.growType = "auto-height"; }
    if (n.t === "inst") {
      for (const [child, chars] of Object.entries(n.texts || {})) {
        const t = penpotUtils.findShape((x) => x.type === "text" && x.name === child, s);
        if (!t) throw new Error("text '" + child + "' not found in " + n.set);
        t.characters = String(chars);
      }
      for (const h of n.hide || []) { const x = penpotUtils.findShape((y) => y.name === h, s); if (!x) throw new Error("layer '" + h + "' not found in " + n.set); x.hidden = true; }
      for (const h of n.show || []) { const x = penpotUtils.findShape((y) => y.name === h, s); if (!x) throw new Error("layer '" + h + "' not found in " + n.set); x.hidden = false; }
      if (n.w || n.h) s.resize(n.w || s.width, n.h || s.height);
    }
  };
  // v4: expand style refs ("s": key -> Object.assign({}, styles[key], node) without "s"), recursively over kids.
  // Returns a new tree; the input is not changed.
  S.expand = (n, styles) => {
    if (!n || typeof n !== "object" || Array.isArray(n)) return n;
    let x = n;
    if (own(n, "s")) {
      const st = styles && typeof styles === "object" && own(styles, n.s) ? styles[n.s] : null;
      if (!st || typeof st !== "object" || Array.isArray(st)) throw new Error("unknown style key '" + n.s + "' on " + (n.name || "?"));
      if (own(st, "s")) throw new Error("style '" + n.s + "' carries a style key itself");
      x = Object.assign({}, st, n);
      delete x.s;
    }
    if (Array.isArray(x.kids)) x = Object.assign({}, x, { kids: x.kids.map((k) => S.expand(k, styles)) });
    return x;
  };
  // v4.1: the one node of `list` with this name; throws when there is none or more than one.
  const only = (list, name, what, where) => {
    const hits = list.filter((x) => x && x.name === name);
    if (hits.length === 1) return hits[0];
    throw new Error(what + " '" + name + "' " + (hits.length ? "is not unique (" + hits.length + " siblings)" : "not found") + " " + where);
  };
  const jcopy = (x) => JSON.parse(JSON.stringify(x));
  // v4.1: the node a clone stands for (see the header); `earlier` = the earlier siblings, already resolved. Every key,
  // path and texts layer is checked here, before anything is drawn.
  const resolveClone = (k, earlier) => {
    for (const f of Object.keys(k)) if (KEYS.clone.indexOf(f) < 0) throw new Error("unknown key '" + f + "' on clone " + k.name);
    if (!k.name) throw new Error("node without a name (clone)");
    if (!k.of) throw new Error("clone without 'of': " + k.name);
    if (k.set !== undefined && !isObj(k.set)) throw new Error("bad set on clone " + k.name);
    if (k.texts !== undefined && !isObj(k.texts)) throw new Error("bad texts on clone " + k.name);
    const sets = Object.entries(k.set || {});
    for (const [p, o] of sets) {
      if (!isObj(o)) throw new Error("bad set entry " + JSON.stringify(p) + " on clone " + k.name);
      for (const f of Object.keys(o)) if (SET_KEYS.indexOf(f) < 0) throw new Error("unknown set key '" + f + "' at " + JSON.stringify(p) + " on clone " + k.name);
    }
    const c = jcopy(only(earlier, k.of, "clone source", "among the earlier siblings of " + k.name));
    c.name = k.name;
    for (const [p, o] of sets) {
      let t = c;
      for (const seg of String(p).split("/").filter(Boolean)) t = only(Array.isArray(t.kids) ? t.kids : [], seg, "path " + JSON.stringify(p) + ": segment", "in " + k.of);
      if (t.t !== "text") throw new Error("set target " + JSON.stringify(p) + " is a " + t.t + ", not a text, in " + k.of);
      for (const f of SET_KEYS) if (own(o, f)) t[f] = o[f];
    }
    for (const [layer, chars] of Object.entries(k.texts || {})) {
      if (c.t !== "inst" || !isObj(c.texts) || !own(c.texts, layer)) throw new Error("text '" + layer + "' is not a texts key of the inst " + k.of);
      c.texts[layer] = chars;
    }
    for (const f of ["x", "y", "abs"]) if (own(k, f)) c[f] = k[f];
    return c;
  };
  // v4.1: a copy of the tree with every clone node replaced by the node it stands for, like compact.py materialize():
  // kids left to right, so a source's own clones are resolved before it is copied. The input is not changed.
  S.resolve = (n) => {
    if (n && n.t === "clone") throw new Error("clone '" + n.name + "' at a section root: a clone copies an earlier sibling in the same section JSON (v4.1 never uses shape.clone(), and the shape drawn by an earlier call has no JSON here); give the node itself");
    if (!n || typeof n !== "object" || !Array.isArray(n.kids)) return n;
    const out = [];
    for (const k of n.kids) out.push(k && k.t === "clone" ? resolveClone(k, out) : S.resolve(k));
    return Object.assign({}, n, { kids: out });
  };
  // Draw a resolved node tree under parent (at index, or appended). Returns the created shape.
  const draw = (n, parent, index) => {
    const s = make(n);
    if (index !== undefined && index >= 0) parent.insertChild(index, s); else parent.appendChild(s);
    finish(s, n);
    place(s, n, parent);
    if (n.t === "board") for (const k of n.kids || []) draw(k, s);
    return s;
  };
  // Render a node tree under parent (at index, or appended). Returns the created shape. v4.1: clones resolved first.
  S.render = (n, parent, index) => draw(S.resolve(n), parent, index);
  // Replace the direct child named like the node (keeps its index), or append it. v4.1: the clones are resolved (and
  // checked) before the old child is removed.
  S.put = (parent, n) => {
    const r = S.resolve(n);
    const old = S.child(parent, r.name);
    let at;
    // v3.1: children are proxies, so indexOf() is always -1; find the old child's index by id
    if (old) { at = parent.children.findIndex((c) => c.id === old.id); old.remove(); }
    return draw(r, parent, at);
  };
  // Find-or-create a page-root board by exact name. o: cv.board options; w, h, x, y in page px.
  S.root = (name, spec) => S.memo(() => {
    const cv = cvl();
    const hits = penpot.currentPage.root.children.filter((c) => c.name === name && c.type === "board");
    if (hits.length > 1) throw new Error("duplicate root boards named " + name + ": " + hits.length);
    if (hits.length === 1) return hits[0];
    const b = cv.board(name, (spec && spec.o) || {});
    padSides(b, spec && spec.o);
    penpot.currentPage.root.appendChild(b);
    if (spec && (spec.w || spec.h)) b.resize(spec.w || b.width, spec.h || b.height);
    if (b.flex && spec) {
      const o = spec.o || {};
      b.flex.horizontalSizing = spec.w ? "fix" : (o.hs || "auto");
      b.flex.verticalSizing = spec.h ? "fix" : (o.vs || "auto");
    }
    b.x = spec && spec.x !== undefined ? spec.x : 0;
    b.y = spec && spec.y !== undefined ? spec.y : 0;
    cv.tag(b, "sheet-root");
    return b;
  });
  // Resolve a "/"-separated path of child names under root ("" = root itself).
  S.at = (root, path) => {
    let cur = root;
    for (const seg of String(path || "").split("/").filter(Boolean)) {
      const nx = S.child(cur, seg);
      if (!nx) throw new Error("path not found: " + path + " (at " + seg + ")");
      cur = nx;
    }
    return cur;
  };
  // Render one sheet section { into, node, styles? } under root (v4: style refs are expanded first; v4.1: then clones
  // are resolved, with the token memo for this run only).
  S.section = (root, sec) => S.memo(() => S.put(S.at(root, sec.into), S.expand(sec.node, sec.styles || null)));
  // v4.2: the deferred per-side padding re-assignment (see the header). A board qualifies when its bound padding tokens
  // do not fit the simple pattern; it is re-assigned only once its bound sides hold their tokens' values (the binds have
  // landed), with its current values, through the setters in v3.1's order (top, right, bottom, left). S.padsDone maps a
  // board id to the values it was re-assigned with in this plugin session; a board is done again only if they change.
  // Returns { fixed, pending }: re-assigned now, and qualifying boards whose binds have not landed yet.
  const PAD_TK = ["paddingTop", "paddingRight", "paddingBottom", "paddingLeft"];
  const PAD_F = ["topPadding", "rightPadding", "bottomPadding", "leftPadding"];
  const padInComp = (s) => { try { return s.isComponentInstance() || s.isComponentMainInstance(); } catch (e) { return false; } };
  const tokPx = (cv, name) => {
    let t = null;
    try { t = cv.T(name); } catch (e) { return NaN; }
    return typeof t.resolvedValue === "number" ? t.resolvedValue : parseFloat(t.resolvedValueString || t.value);
  };
  S.padsDone = new Map();
  S.pads = (root) => S.memo(() => {
    const cv = cvl();
    let fixed = 0, pending = 0;
    const seen = new Set();
    const bs = penpotUtils.findShapes((s) => s.type === "board" && !!s.flex && !padInComp(s), root);
    if (root.type === "board" && root.flex && !padInComp(root)) bs.push(root);
    for (const s of bs) {
      if (seen.has(s.id)) continue;
      seen.add(s.id);
      let tk = {};
      try { tk = s.tokens || {}; } catch (e) { tk = {}; }
      const names = PAD_TK.map((p) => tk[p] || null);
      if (!names.some(Boolean) || (names[0] === names[2] && names[1] === names[3])) continue;
      const f = s.flex;
      const v = PAD_F.map((k) => f[k]);
      const key = v.join(",");
      if (S.padsDone.get(s.id) === key) continue;
      const landed = names.every((n, i) => {
        if (!n) return true;
        const px = tokPx(cv, n);
        return Number.isFinite(px) ? Math.abs(v[i] - px) < 0.01 : v[i] > 0;
      });
      if (!landed) { pending++; continue; }
      for (let i = 0; i < 4; i++) f[PAD_F[i]] = v[i];
      S.padsDone.set(s.id, key);
      fixed++;
    }
    return { fixed, pending };
  });
  // A small read-back: shape and text counts, unmeasured texts, children names. v4.2: S.pads(root) runs first (a failure
  // is reported as padsError and never stops the report); padsFixed and padsPending come last.
  S.report = (root) => {
    let pads = { fixed: 0, pending: 0 };
    let padsError = null;
    try { pads = S.pads(root); } catch (e) { padsError = String(e && e.message ? e.message : e).slice(0, 160); }
    const all = penpotUtils.findShapes(() => true, root);
    const out = {
      id: root.id, name: root.name, w: Math.round(root.width), h: Math.round(root.height), shapes: all.length,
      texts: all.filter((s) => s.type === "text").length,
      unmeasured: all.filter((s) => s.type === "text" && s.height <= 1).length,
      kids: (root.children || []).map((c) => c.name),
      padsFixed: pads.fixed, padsPending: pads.pending,
    };
    if (padsError) out.padsError = padsError;
    return out;
  };
  // v4: read-only layout lint (run after touch + relayout, in a later call than the sections). Hidden shapes and their
  // subtrees are skipped. Returns { counts: {kind: n}, findings: [{ kind, path, detail }] (at most 40, depth-first),
  // shapes } with path = child names from the root joined by "/". Kinds:
  //   text-overflow: a text's box extends more than 0.5 px past its nearest board ancestor's box (either axis); v4.1:
  //                  not for a direct child of the root that is already reported as outside-root
  //   outside-root : a shape's box extends more than 0.5 px past the root's box (only the outermost such shape)
  //   unmeasured   : a text with height <= 1 (not also checked for overflow)
  //   overlap      : two sibling texts or boards of a board intersecting by more than 1 px on both axes. v4.1: in a flex
  //                  board only pairs with an absolute child; never among the layers of a component copy or main; not
  //                  when the earlier sibling strictly contains the later one (a background under overlays), while
  //                  same-size stacking is reported
  //   unbound      : (v4.1) a text made by cvlib (shared plugin data cvd02/kind "text", outside component copies) that
  //                  has no typography or no fill token bind
  S.lint = (root) => {
    const MAX = 40;
    const counts = { "text-overflow": 0, "outside-root": 0, unmeasured: 0, overlap: 0, unbound: 0 };
    const findings = [];
    let shapes = 0;
    const add = (kind, path, detail) => { counts[kind]++; if (findings.length < MAX) findings.push({ kind, path, detail }); };
    const r1 = (v) => Math.round(v * 10) / 10;
    const box = (s) => ({ x0: s.x, y0: s.y, x1: s.x + s.width, y1: s.y + s.height });
    const past = (a, b, tol) => {
      const d = [["left", b.x0 - a.x0], ["top", b.y0 - a.y0], ["right", a.x1 - b.x1], ["bottom", a.y1 - b.y1]].filter((e) => e[1] > tol);
      return d.length ? d.map((e) => e[0] + " " + r1(e[1])).join(", ") : null;
    };
    // v4.1 helpers; a getter that throws counts as "no"
    const tokensOf = (s) => { try { return s.tokens || {}; } catch (e) { return {}; } };
    const kindOf = (s) => { try { return s.getSharedPluginData("cvd02", "kind"); } catch (e) { return null; } };
    const isAbs = (s) => { try { return !!(s.layoutChild && s.layoutChild.absolute); } catch (e) { return false; } };
    const inComp = (s) => { try { return s.isComponentInstance() || s.isComponentMainInstance(); } catch (e) { return false; } };
    const area = (a) => (a.x1 - a.x0) * (a.y1 - a.y0);
    const contains = (a, b) => a.x0 <= b.x0 + 0.5 && a.y0 <= b.y0 + 0.5 && a.x1 >= b.x1 - 0.5 && a.y1 >= b.y1 - 0.5 && area(a) > area(b);
    const R = box(root);
    const visit = (parent, ppath, board, outside) => {
      const kids = (parent.children || []).filter((k) => !k.hidden);
      for (const s of kids) {
        shapes++;
        const path = ppath ? ppath + "/" + s.name : s.name;
        const b = box(s);
        let out = outside;
        let outHere = false;
        if (!out) {
          const p = past(b, R, 0.5);
          if (p) { add("outside-root", path, p + " px past the root"); out = true; outHere = true; }
        }
        if (s.type === "text") {
          if (!(s.height > 1)) add("unmeasured", path, "height " + r1(s.height));
          else if (board && !(outHere && board === root)) {
            const p = past(b, box(board), 0.5);
            if (p) add("text-overflow", path, p + " px past board '" + board.name + "'");
          }
          if (kindOf(s) === "text" && !inComp(s)) {
            const tk = tokensOf(s);
            const miss = ["typography", "fill"].filter((p) => !tk[p]);
            if (miss.length) add("unbound", path, "no " + miss.join(" and no ") + " token");
          }
        }
        const sub = s.children;
        if (sub && sub.length) visit(s, path, s.type === "board" ? s : board, out);
      }
      if (parent.type === "board" && !inComp(parent)) {
        const flex = !!parent.flex;
        const sib = kids.filter((k) => k.type === "text" || k.type === "board");
        const bx = sib.map(box);
        const ab = sib.map((k) => flex && isAbs(k));
        for (let i = 0; i < sib.length; i++) {
          for (let j = i + 1; j < sib.length; j++) {
            if (flex && !ab[i] && !ab[j]) continue; // in-flow children of a flex board are placed by the layout
            if (contains(bx[i], bx[j])) continue;
            const w = Math.min(bx[i].x1, bx[j].x1) - Math.max(bx[i].x0, bx[j].x0);
            const h = Math.min(bx[i].y1, bx[j].y1) - Math.max(bx[i].y0, bx[j].y0);
            if (w > 1 && h > 1) add("overlap", ppath ? ppath + "/" + sib[j].name : sib[j].name, "overlaps '" + sib[i].name + "' by " + r1(w) + " x " + r1(h) + " px");
          }
        }
      }
    };
    visit(root, "", root.type === "board" ? root : null, false);
    return { counts, findings, shapes };
  };
  storage.cvsheet = S;
}
