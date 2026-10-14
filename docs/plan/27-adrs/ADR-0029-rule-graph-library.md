# ADR-0029: Rule node-graph library and layout placement

- Status: Accepted (2026-10-14)
- Date: 2026-10-04
- Note: headless measurement accepted by owner 2026-10-14 (#1778); Electron/reference-hardware run deferred to E37-Q04
- Ticket: E37-K01; evidence: `docs/plan/spikes/E37-K01.md`

## Context
SCR-082 needs 200 nodes at 60 fps and a keyboard-operable connect flow; CMP-146 requires DOM-rendered nodes for
the a11y mirror.

## Decision
1. Use **@xyflow/react (React Flow) 12.x, pinned exactly**, with fully controlled `nodes`/`edges` owned by
   `packages/rule-graph`. Ports are our own focusable elements; connect is a keyboard state machine in our code.
2. **Provisional soft cap of 120 nodes** (warning banner, no hard block), already written into SCR-082
   (`14-screens-catalogue.md`) and E37-S01, because React Flow measured ~21 fps at 4x CPU throttle. E37-Q04
   re-measures on reference hardware and in Electron and lifts the cap if >= 45 fps at 200 nodes.
3. **Auto-layout runs in a web worker** using **dagre** (@dagrejs/dagre); elkjs only if routing needs justify
   its ~442 KB gz cost. Main-thread layout at 200 nodes measured ~230 ms (> 100 ms limit).
4. `graph_layout` is persisted separately and excluded from the canonical IR hash (ADR-0026).
5. Rete.js is the fallback if E37-S02 finds a keyboard blocker requiring a fork, or if E37-Q04 measures < 45 fps
   at 200 nodes on reference hardware/Electron (spike: React Flow 21 fps at 4x CPU throttle; minimal Rete 57 fps,
   lower bound only).

## Consequences
Editor route is lazy-loaded (~60 KB gz library delta). Dependency additions need licence/SCA review in E37-T01.
Confidence is bounded by the spike's limitations (headless Chromium, non-reference hardware).

## Failure path and re-estimates (cap executed; point changes await owner confirmation)
If React Flow is rejected (E37-Q04 fps < 45, or E37-S02 needs a fork), switch to Rete.js behind the same
`packages/rule-graph` adapter (controlled nodes/edges, our own ports), so IR, layout and the a11y mirror are unchanged.

| Ticket | Baseline impact (any path) | Failure-path impact (Rete) |
|---|---|---|
| E37-T02 (auto-layout) | + worker + dagre message protocol: ~+1 pt | none extra (layout is library-agnostic) |
| E37-S01 (canvas/nodes) | none | + render plugin, own connection geometry, selection model: ~+3 to +5 pts |
| E37-S02 (keyboard connect) | + arrow traversal, roving tabindex, edge focus/delete: ~+2 pts | ~+3 pts more (no `nodesFocusable`) |
| E37-Q04 | + 4x throttle and Electron/reference-HW run: ~+1 pt | becomes the decision gate, runs first |

Mitigation before switching: the 120-node cap (now applied in SCR-082/E37-S01) and a reduced-chrome mode. Ticket estimate fields are deliberately unchanged: they feed the owner-approved sprint plan, so the point changes above are applied only on owner approval. Points are the spike author's
estimates, not owner-approved; no risk-register change.
