---
description: Standing gates for design specs (docs/design/**) — the E09-D09 T2 disabled-form checklist, the reason vocabulary and the recurring a11y / contract-pinning items; applied by every design writer brief and pre-lens brief
---

# Design specs — standing gates

Owners (normative; this file is a checklist that points at them, C-16.5 — if it ever disagrees, they win and
this file is a bug): the decision rule for gated controls is `docs/plan/14-screens-catalogue.md` §0.5 rule 5;
its anatomy, reason vocabulary and keyboard rules are `docs/design/E09/E09-D09.md` §2.1–§2.2, §3.1–§3.2 and
§9.1–§9.3; the accessibility floors are `docs/plan/05-accessibility-standard.md` §3.1, §3.4 and §5; the arm
rule is `docs/plan/22-api-openapi.yaml` (`ArmToken`); Penpot references follow `docs/design/README.md`.
Shorthand: `05`, `14`, `15`, `22` are the `docs/plan/` documents by number.

Terms (this file): a **pre-lens** is the lane's own review of a spec before it posts READY for the
orchestrator's round. A **G-T2 miss is a Major** in the pre-lens; a **Recurring-item miss is a Minor**.

## G-T2 — the controls E09-D09 §2.1 routes to T2 are specified as T2

Scope: a control that `14` §0.5 rule 5 and E09-D09 §2.1 steps 3–4 route to **T2 "disabled with a visible
reason"** — gated by permission, grant, account, environment or a registered state. Not in scope, because the
owner routes them elsewhere: admin navigation affordances (T3 hidden — the one mandatory hiding case, §2.1
step 1, anti-enumeration), server refusals (T4, step 2), a missing step-up and the three-strike read-only
state (T1 / a step-2 refusal today, §2.1 and §3.3), and form-validity disabling (outside the grammar, §9.1).
Within scope, the spec must state once and cite from every section that shows a T2 control:

- **G-T2.1a** (§2.2, §9.1): the control keeps its native role and its **full label**.
- **G-T2.1b** (§9.1): `aria-disabled="true"`, never the `disabled` attribute — it stays in the Tab order and a
  menu item stays arrow-reachable.
- **G-T2.1c** (§2.2, §9.2): the reason node is in the DOM at mount and linked by `aria-describedby`; rendering
  2a (inline) by default, 2b (tooltip echo) only for icon-only controls and toolbar segments without room,
  and the sentence form where the owner names it.
- **G-T2.1d** (§2.2, §8): CMP-079 RbacGate wraps every §2.1 step-3 leg; the CMP-019 `lock` glyph
  (`decorative=false`, accessible name "Not available") leads the label.
- **G-T2.2** (§2.2, §11): hi-fi label `color.text.tertiary`, reason `color.text.secondary`; for primary / buy /
  sell actions the fill becomes `color.surface.raised` with a `color.border.default` hairline; **never
  `color.text.disabled`, never `opacity.disabled`** on the label, glyph or reason. The token pins are §8
  DS-1's interim aliases — re-read §8 if the DS re-aliases them. Wireframes (this file): the T2 label is drawn
  in the wireframe's mid grey, never in the grey reserved for placeholder or disabled text, and every T2
  frame draws the glyph, the full label and the reason.
- **G-T2.3** (§9.3): `Enter`, `Space` or a bound hotkey on a T2 control changes nothing and re-shows the reason
  inline with one polite announcement; arrow keys land on a disabled menu item without activating it.
- **G-T2.4** (§3.1–§3.2): every reason is one of §3.1's keys (`{verb}` only on `rbac.permission` and
  `rbac.owner_only`, from the §3.2 verb table) or a key of a state vocabulary §3.1 registers; one sentence,
  ≤ 60 characters, full stop; it names a capability, never data — no balance, position, symbol, count, route,
  screen name or user name except the view-as target (`rbac.view_as`); a screen never writes its own string.
  (This file:) a verb the §3.2 table lacks is routed as an amendment to E09-D09 §3.2; a state string the
  registered vocabularies lack is a PROPOSED key with the vocabulary owner named.
- **G-T2.5** (§2.2 "one notice, many pointers"): a panel that is read-only for the session carries one
  panel-header notice; every gated control's `aria-describedby` points at that node.
- **G-T2.6** (this file; E09-D09 §7–§8 practise it): T2 is named in every state row and frame that shows a
  gated control; CMP-079 and CMP-019 `lock` appear in every component list and component amendment that
  covers those surfaces.

## Recurring items (Minors; each has been a carry more than once)

- **R1 Text resize** (`05` §5 item 7, WCAG 1.4.4): for every dialog, drawer and fixed-height region, say what
  reflows at 200 % zoom and the in-app text scale at 1280 × 800.
- **R2 Forced colours** (this file): name the `forced-colors` rendering for every colour-only carrier, or hand
  it to the hi-fi spec in the hand-off section.
- **R3 Keyboard model** (`05` §3.1 item 1, §3.4 items 2, 4 and 6): initial focus, the Tab order across columns
  and sticky footers, what `Enter` does in a field, where focus returns on close; a table that moves rows with
  arrows is the APG grid or a focusable scroll region, named.
- **R4 Frames** (`docs/design/README.md`): every state the text names has a frame or a named inset; the frame
  list and the state tables reconcile.
- **R5 Live accounts** (`22` `ArmToken`): submits — `placeOrder`, `createTradeGroup`, reduce-only ones and
  risk-increasing amends, reverse and leverage changes included — need the arm; cancels, `closePosition`,
  `closeAllPositions`, quantity-reducing amends, take-profit changes and attaching or tightening a stop are
  never refused for want of it (C-2.6) — a spec must not gate those.
- **R6 Contracts in flight** (open PRs): pin them at their current head sha, re-read them before every commit,
  quote their vocabulary exactly, qualify "if #N merges as is", and re-pin to the merge commit once merged.
- **R7 Penpot references** (`docs/design/README.md`): page name and page id only — never an instance
  hostname, team or file URL, in the spec, the tool, the body or a commit, including values assembled from
  split string literals.
