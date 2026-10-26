# Design tooling — Penpot (owner decision 2026-09-25)

UI/UX tickets (`E*-D*`, screens `SCR-*`, components `CMP-*`) are executed in **Penpot** (open-source,
MPL-2.0) instead of Figma. Agents drive it through the **official Penpot MCP server**, which exposes
`high_level_overview`, `penpot_api_info`, `execute_code` (Penpot Plugin API), `export_shape`, `import_image`.

## Topology

| Piece           | Where                                                                                                                                                                 | Notes                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| --------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Penpot instance | **Self-hosted Penpot 2.18** since 2026-10-21 (URL, team/file ids and credentials: owner's private notes)                                                              | **Never write the instance URL, team/file ids or credentials in this repository or in PR text** (public repo). Page ids were preserved by the import, so existing page-id references stay valid. The SaaS file is a read-only backup.                                                                                                                                                                                                                                          |
| MCP server      | **Hosted:** `<instance>/mcp/stream?userToken=<MCP key>` (Streamable HTTP)                                                                                             | Registered at **local scope** as `penpot`, **one key per lane**, created under _Your account → Integrations → MCP Server_. Keys never go in the repo, messages or logs. Tools: `high_level_overview`, `penpot_api_info`, `execute_code`, `export_shape` (no `import_image` on hosted).                                                                                                                                                                                         |
| Plugin          | Penpot's built-in **MCP plugin** (Plugins menu in any open file; the toolbar **MCP** toggle keeps the connection alive)                                               | The plugin _is_ the bridge: without an open, connected plugin every tool call fails with "No plugin instance connected". Re-enable the toolbar **MCP** toggle after any page reload.                                                                                                                                                                                                                                                                                           |
| Files           | **One Penpot file per design set** (since 2026-10-26, [PENPOT-FILES-1]): `E<nn>-D<nn> boards`, created by the lane's own account in the team's default project        | The 92-page shared file stopped loading in lane tabs, so it holds only boards drawn before that date (repairs go through the builder) and the shared design-system library, which each set file connects to. Tokens are file-local in Penpot: recreate them in every new file with `docs/design/_tools/penpot_token_sets.py` (`--check`, then `--emit-js <set>` per set and `--emit-js themes` last, run through the plugin). References stay file name + page name + page id. |
| Local fallback  | a local checkout of Penpot's `mcp` package (path in the contributor's private notes) → `start-penpot-mcp.cmd` (`:4401/mcp`, plugin `:4400/manifest.json`, WS `:4402`) | Built 2026-09-25 from Penpot `develop`. Use if the hosted endpoint is down.                                                                                                                                                                                                                                                                                                                                                                                                    |

## Session ritual (human, once per session)

1. Open the design file in Penpot in a browser tab.
2. Plugins menu → **Penpot MCP** → **Connect**. The toolbar **MCP** toggle is the control that keeps the connection
   alive: re-enable it after any page reload (it reads Off afterwards).
3. Keep that tab and the plugin panel open for the whole agent session (browser tab suspension drops the bridge).

## Fonts

Team fonts uploaded 2026-09-25: **Inter** v4.1 and **JetBrains Mono** v2.304, each as 8 static TTFs
(Regular/Medium/SemiBold/Bold + italics = weight tokens 400/500/600/700). JetBrains Mono needed its Macintosh
`name` records stripped (fontTools): opentype.js 2.x `getEnglishName()` reads only the first platform table
present, so Penpot silently skipped the files (upstream bug, to be filed). Fixed set: the contributor's local fonts
folder (the JetBrains Mono fixed build). The file uses the Google fonts `gfont-inter` / `gfont-jetbrains-mono`; valid
`fontVariantId` values are `regular`, `500`, `600`, `700` (+ italic forms); look fonts up exactly
(`penpot.fonts.all.find(f => f.fontId === 'gfont-inter')`) because Penpot 2.18's `findByName`/`findById` match
case-insensitive substrings, not only prefixes (`Inter` or `gfont-inter` also hit Inter Tight).

## Approval rule (owner decision 2026-09-25) — **every UI/UX design ticket requires human approval**

Design agents work **Suggest → Apply-with-review**: they may build into the ticket's Penpot page, but a design
ticket only moves to **Done** when the owner has approved it. Concretely:

1. Agent builds the frames on the ticket's page (naming per §Rules), exports PNGs, writes the spec PR.
2. Agent sets Status **In Review**, and posts on the issue: Penpot page reference + PNG exports + a ≤10-line summary of
   decisions taken and open questions. It does **not** merge the spec PR.

**Mandatory evidence on EVERY design ticket — no exceptions for "research" or "wireframe" tickets (owner decision
2026-09-25).** A design PR without both of the following is incomplete and must be sent back:

- **Penpot reference** to the ticket's page, in the PR body _and_ the issue comment: the page **name + page id**, e.g.
  `` Page `E42-D02` · id `<page-id>` `` — read `page.id` from the plugin API (`penpotUtils.getPageByName(...).id`).
  Never paste the instance hostname or a team/file/workspace URL into public text (PR bodies, specs, comments); old
  SaaS links in merged documents are historical.
- **Screenshots**: one PNG per frame/state exported with `docs/design/_tools/penpot_export.py`, committed under
  `docs/design/<epic>/img/`, and **embedded** in the PR body (`![SCR-nnn/state](../docs/design/<epic>/img/<name>.png)`
  or the raw GitHub URL) so the owner can review without opening Penpot.
- UX-research tickets still design in Penpot: the artefact is a research board (personas/journey/findings cards,
  comparison matrices, annotated wireframes) on the ticket's page — not a markdown file alone. Journey maps and
  flows are drawn as frames; Mermaid may be _additional_, never the only deliverable.
- The `code-reviewer` for a design PR fails the review (`REQUEST_CHANGES`) if either item is missing.

3. Owner reviews in Penpot (and the PR). Approval = **owner merges the spec PR** and/or comments `approved`.
   Any other comment = rework; agent iterates on the same page.
4. Only after approval may the dependent frontend ticket enter Ready (design-ahead rule, C-11.1).

Agents never delete or restructure pages/components they did not create in the current ticket, never touch the
shared DS library file without an explicit ticket, and never call `execute_code` on a file other than the one named
in the ticket. Long scripts (board, relayout and dedupe scripts) go through `docs/design/_tools/penpot_exec.py`
(same `--server`/`--project`/`--endpoint` flags as `penpot_export.py`) instead of being pasted into `execute_code`;
the same rule applies to them. Skills: the official `penpot-*` skill set (penpot-ai-kit 0.4.0) is installed in
`~/.claude/skills/`;
`penpot-router` picks the skill, `penpot-foundations` owns tokens, `penpot-build-screen` owns screens,
`penpot-component-factory` owns `CMP-*`, `penpot-audit-accessibility` runs before every hand-off.

## Rules for design agents

- One Penpot **file per epic**, one **page per screen** (`SCR-nnn <name>`); components live in the shared
  **CandleViewer DS** library file (`packages/ui` tokens are the source of truth — never invent a token).
- Deliverables per design ticket (all of these, or the ticket is not Done):
  1. Penpot artefacts (frames named `SCR-nnn/<state>`; every state in `14-screens-catalogue.md`).
  2. `docs/design/<epic>/<ticket>.md` — spec: purpose, states, data, interactions, hotkeys, a11y notes,
     token usage, and **PNG exports** of each frame (`export_shape`) committed under `docs/design/<epic>/img/`.
  3. Storybook stories for any `CMP-*` touched (`packages/ui`).
  4. For `CMP-*` tickets (and `SCR-*` tickets that change a component contract): the handoff checklist
     `docs/design/<epic>/<ticket>-handoff.md`, per `16-design-system-brief.md` §11.4 / §13.3 item 8.
- Design sign-off = PR merge of the spec + exports; the Penpot reference goes in the ticket comment.
- `execute_code` runs arbitrary JS in the plugin sandbox: only mutate the file named in the ticket; never
  delete pages/components you did not create; export before and after large mutations.

## Penpot plugin-API gotchas (learned 2026-09-25, E05-D01)

- **Cascade is not synchronous.** Setting `token.value` from the plugin API updates `resolvedValue` but bound shapes
  re-paint only on a propagation event — toggle the active theme off/on (`theme.toggleActive()` ×2) after bulk token
  edits. Changing a token in the Penpot UI propagates immediately.
- Token names are paths: a token cannot exist at a path that is a prefix of another (`color.buy` vs `color.buy.hover`).
  Convention: the leaf is `.default`.
- `applyToken(tok, ["all"])` fails for radius; pass the four `borderRadius*` props explicitly.
- `penpot.currentPage` / `file.name` are read-only from the API; place shapes on another page with
  `page.root.appendChild(shape)`.
- Export from code: `await shape.export({type:"png", scale:1})` returns a `Uint8Array`.
- **Browser tab suspension** kills the bridge within ~30–45 s of the tab losing focus. Before an agent session:
  pin the Penpot tab, Chrome → Settings → Performance → _Always keep these sites active_ → the Penpot instance's
  origin, and disable Memory Saver for it. Without this, every design ticket stalls.
- **A page reload closes the MCP plugin panel** (the toolbar **MCP** toggle reads Off afterwards) — re-enable it after
  any reload. Chrome throttles non-foreground windows, so keep the building window in front or start Chrome with
  `--disable-background-timer-throttling --disable-renderer-backgrounding --disable-backgrounding-occluded-windows`.
