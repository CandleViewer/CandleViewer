# Design specs — standing gates

Source (normative, single owner): `docs/design/E09/E09-D09.md` §2.2 (the T2 treatment), §3.1–§3.2 (the reason
vocabulary and the verb table), §9.1–§9.3 (`aria-disabled`, `aria-describedby`, the keys on a T2 control);
the decision rule itself lives in `docs/plan/14-screens-catalogue.md` §0.5 rule 5. Accessibility floors:
`docs/plan/05-accessibility-standard.md` §3.4 and §5. This file is a checklist that points at them (C-16.5);
if it ever disagrees with those documents, they win and this file is a bug.

Why it exists: the T2 disabled form was a Major in four orchestrator text rounds and five pre-lens findings
on 2026-10-22 across two design lanes. Every writer brief and every pre-lens brief for a design ticket
applies this list; a miss is a **Major** in the pre-lens, before the orchestrator's round.

## G-T2 — every gated control is E09-D09's T2

A control gated by role, grant, environment, session state or a registered system state must be specified as
E09-D09 §2.2's **T2 "disabled with a visible reason"**, never as plain "disabled". The spec must state, once,
and cite from every section that shows a gated control:

1. **Semantics** (§2.2, §9.1, §9.2): the native role and the **full label** are kept; `aria-disabled="true"`,
   never the `disabled` attribute (the control stays in the Tab order; a menu item stays arrow-reachable); the
   reason node is in the DOM at mount and linked by `aria-describedby`; role legs are wrapped in CMP-079
   RbacGate; the `lock` glyph is CMP-019 (`decorative=false`, name "Not available") leading the label.
2. **Visual** (§2.2): hi-fi label `color.text.tertiary`, reason `color.text.secondary`, fill
   `color.surface.raised` with a `color.border.default` hairline — **never `color.text.disabled`, never
   `opacity.disabled`**; wireframes draw the label in the middle grey, never the lightest; boards draw the
   glyph, the full label and the reason.
3. **Keys** (§9.3): `Enter`, `Space`, a bound hotkey or an arrow on a T2 radio change nothing (stage nothing) and
   re-show the reason inline with one polite announcement.
4. **Reasons** (§3.1–§3.2): an `rbac.*` key with a verb from the §3.2 verb table (an unregistered verb needs an
   A-row to §3.2) or a registered state-vocabulary key (E30-D02 §14, E17-D01 §7); a screen never writes its own
   string; a reason names a capability, never data (no symbol, count, balance, user name); new state strings are
   PROPOSED keys with the vocabulary owner named.
5. **Read-only panels** (§2.2 "one notice, many pointers"): one panel notice under the header; every gated
   control's `aria-describedby` points at it.
6. **Naming**: T2 named in every state row and frame that shows a gated control; CMP-079 and CMP-019 `lock` in
   every component list and component amendment covering those surfaces.

## Recurring Minors to pre-empt (each has been a carry more than once)

- **200 % zoom and the in-app text scale** (`05` §5 item 7, WCAG 1.4.4): say what reflows for every dialog,
  drawer and fixed-height region at 1280 × 800; name the `forced-colors` rendering for colour-only carriers or
  hand both to the hi-fi spec in the hand-off section.
- **A complete keyboard model per dialog and grid** (`05` §3.4): initial focus, the Tab order across columns
  and sticky footers, what `Enter` does in a field, where focus returns on close; a table that moves rows with
  arrows is the APG grid or a focusable scroll region, named.
- **Frames**: every state the text names has a frame or a named inset; the frame list and the state tables
  reconcile.
- **Live accounts**: every submit needs the arm (`22` `X-Arm-Token`), retries and reduce-only ones included.
- **Contracts in flight** (open PRs): pin them at their current head sha, re-read them before every commit,
  quote their vocabulary exactly, qualify "if #N merges as is", and re-pin to the merge commit once merged.
- **Penpot references**: a page is cited by name and page id only — never an instance hostname, team or file
  URL, in the spec, the tool, the body or a commit (including values assembled from split string literals).
