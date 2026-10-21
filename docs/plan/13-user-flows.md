# 13 — User Flows (CandleViewer)

Date: 2026-09-14 · Owner: basiltt · Status: **Baseline for design & backlog**

Scope: web app only, React + custom WebGL engine, Electron shell. All flows below reference personas from `10-personas.md` (P1 Owner, P2 Manager, P3 Viewer, P4 Admin-hat, M1 Rule-author mode) and routes/modals from `12-sitemap.md` (`R-###`, `M-###`). Every flow states its **safety invariants** where relevant (native SL backstop, RBAC, step-up auth, Demo/Live isolation) per `24-owner-decisions.md`.

---

## 1. First-run setup & 2FA enrollment

**Actor:** P1 Owner (bootstrap). **Routes:** R-003 → R-002 → R-100.
**Screens:** SCR-016, SCR-003, SCR-002, SCR-001, SCR-020 (see `14-screens-catalogue.md`).

```mermaid
flowchart TD
  A[Launch app, fresh install] --> B{Users table empty?}
  B -->|yes| C["/login/first-run wizard"]
  B -->|no| Z["/login normal flow"]
  C --> D[Step 1: create Owner username + strong password]
  D --> E[Step 2: TOTP enrollment - show QR + secret, require 1 confirm code]
  E --> F{Code valid?}
  F -->|no| E
  F -->|yes| G[Step 3: Tailscale reachability check]
  G --> H{Backend reachable via Tailscale?}
  H -->|no| I[Show remediation: install Tailscale client, join tailnet]
  I --> G
  H -->|yes| J[Step 4: confirm recovery codes shown once, require checkbox ack]
  J --> K[Owner account + Owner role created in Postgres]
  K --> L["/login/first-run permanently disabled - redirect to /login"]
  L --> M[Owner logs in normally: password + TOTP]
  M --> N["/terminal - empty default layout, empty watchlist, recorder off"]
```

**Notes / edge cases**
- Recovery codes (10 single-use) are shown exactly once at step 4; if the Owner closes the wizard without acknowledging, the wizard resumes at step 4 on next launch (codes are not regenerated silently).
- No Bybit account is configured yet — the Terminal shows an empty state prompting "Add your first Bybit account" (links to flow §2).
- If the wizard is abandoned mid-way (app closed), it resumes at the last completed step; partial Owner records are not left in a usable-but-unenrolled state (TOTP enrollment is transactional with account creation).

---

## 2. Add Bybit account & API key (with permission verification)

**Actor:** P4 Admin-hat. **Routes:** R-310 → R-312 (wizard) → R-320/R-321.
**Screens:** SCR-125, SCR-126, SCR-128, SCR-149 (see `14-screens-catalogue.md`).

```mermaid
flowchart TD
  A["/admin/accounts - click Add account"] --> B[M-013: step 1 - label, account type main/sub]
  B --> C{Main or Sub?}
  C -->|Sub| D[Call Bybit create-sub-member via Owner's master key]
  C -->|Main| E[Use existing Bybit master login]
  D --> F[Sub-UID created, cap check: 5 std / 20 Business KYC]
  F --> G{Under cap?}
  G -->|no| H[Block: show cap reached, link to Bybit KYC upgrade info]
  G -->|yes| I[Step 2: create scoped sub-API key]
  E --> I
  I --> J["Set permissions: ContractTrade+Order+Position (checked)<br/>Wallet read-only (checked)<br/>Withdrawal - locked OFF, not editable"]
  J --> K[Set IP whitelist to this backend's egress IP - required, not optional]
  K --> L[Set key expiry - default 90 days, reminder at 75 days]
  L --> M[Submit key material - envelope-encrypted at rest immediately]
  M --> N[Backend calls GET /v5/user/query-api to verify actual granted scopes]
  N --> O{Withdrawal scope present?}
  O -->|yes| P["HARD STOP: reject key, show 'Withdrawal permission detected - revoke on Bybit and re-issue', key discarded not stored"]
  O -->|no| Q{IP whitelist matches backend egress IP?}
  Q -->|no| R[Warn: 'Key has no/incorrect IP whitelist - orders will be rejected by Bybit', allow save with explicit acknowledgement, flagged amber in list]
  Q -->|yes| S{Trade+Position scopes present?}
  S -->|no| T[Warn: insufficient scope, link back to step 2]
  S -->|yes| U[Key verified - stored, status = Active]
  U --> V[Backend fetches instruments-info + wallet-balance as a live smoke test]
  V --> W{Smoke test success?}
  W -->|yes| X[Account shows green 'Verified' badge in /admin/accounts]
  W -->|no| Y[Account shows amber 'Verification pending/failed' + retry action]
  X --> AA["Prompt: create a per-account profile now? -> flow to trade-group/profile setup"]
```

**Safety invariants**
- Withdrawal-capable keys are **never persisted**, even transiently — the verification call happens before the encrypted-store commit is finalized; on hard-stop the plaintext key material is discarded from memory immediately.
- Key material is shown in the UI **exactly once** (at entry) and never re-displayed; `/admin/keys/:keyId` shows metadata only (masked key id suffix, permissions, IP whitelist, expiry) never the secret.
- Every step in this flow writes an audit log entry (key added, verification result, warnings acknowledged).

---

## 3. Create sub-account profile

**Actor:** P4 Admin-hat / P1 Owner. **Routes:** R-330 → R-331.
**Screens:** SCR-130, SCR-131, SCR-132, SCR-133 (see `14-screens-catalogue.md`).

```mermaid
flowchart TD
  A["/admin/profiles - New profile"] --> B[Select target Bybit account/sub-account]
  B --> C[Set leverage - per symbol or global default]
  C --> D["Set sizing rule: % equity | fixed $ | fixed qty | risk-based (ATR/%-stop)"]
  D --> E[Set default SL/TP offsets - ticks / % / R-multiple]
  E --> F[Set risk caps: max position size, max daily loss %, max concurrent positions]
  F --> G[Set allowed symbols list - defaults to instruments-info linear USDT perps, ownercan narrow]
  G --> H{Owner review & save - step-up required}
  H -->|reject| C
  H -->|approve| I[Profile persisted to Postgres, versioned]
  I --> J[Profile available for selection in Trade Group editor and per-account order defaults]
  J --> K[Audit log: profile created/edited, diff recorded]
```

**Notes**
- Profiles are versioned (append new version rather than destructive overwrite) so historical trade-group fan-outs can be traced to the profile version active at execution time (journal traceability).
- Editing a profile that is currently in use by open positions shows a non-blocking warning: "N open positions use this profile — changes apply to new orders only."

---

## 4. Manager onboarding by owner

**Actor:** P4 Admin-hat, creating P2 Manager. **Routes:** R-303.
**Screens:** SCR-121, SCR-123, SCR-122, SCR-017 (see `14-screens-catalogue.md`).

```mermaid
sequenceDiagram
  participant O as Owner (Admin hat)
  participant App as CandleViewer backend
  participant Bybit as Bybit API
  participant M as New Manager

  O->>App: /admin/users/new - enter manager name, contact
  App->>O: Step: select Bybit sub-account (existing or create new, flow #2)
  O->>App: Assign role = manager, grant accounts (1..N sub-accounts)
  App->>O: Step: grant rules:author? (toggle, default off)
  App->>O: Step: risk-limit assignment (feeds Risk Dashboard)
  O->>App: Confirm (step-up TOTP)
  App->>App: Create manager user record, generate Tailscale invite reference
  App-->>O: Show invite instructions (Tailscale ACL entry to be added by owner outside app)
  O->>M: (out of app) Adds manager to Tailscale ACL, shares invite link
  M->>App: First login: set password
  App->>M: Force TOTP enrollment (cannot proceed without it)
  M->>App: Enrolls TOTP, confirms
  App->>M: Terminal loads, scoped to assigned accounts only
  Note over App: If API key for the assigned sub-account has Bybit's 48h new-key restriction, Terminal shows "API key pending - available after <date/time>"; Demo trading remains available meanwhile.
  App->>O: Audit log entry: manager created, accounts granted, timestamp
```

---

## 5. Create trade group & place fan-out order

**Actor:** P1 Owner. **Routes:** R-142 → R-141, then M-001/M-003.
**Screens:** SCR-062, SCR-061, SCR-060, SCR-076 (see `14-screens-catalogue.md`).

```mermaid
flowchart TD
  A["/trade-groups/new"] --> B[Name the group, e.g. 'Core BTC swing']
  B --> C["Select N accounts (M-016 picker) - each shows its active profile summary"]
  C --> D{At least 1 account selected?}
  D -->|no| C
  D -->|yes| E[Preview per-account sizing: shows computed qty per account given group symbol+risk input]
  E --> F[Save trade group]
  F --> G["Later: open order ticket (M-001), select this trade group as target instead of single account"]
  G --> H[Enter symbol, side, order type, base risk/size input]
  H --> I["Per-account preview table: symbol, computed qty (per profile sizing rule), leverage, SL/TP offsets, estimated margin"]
  I --> J{Any account fails pre-validation? e.g. exceeds max position, symbol not allowed}
  J -->|yes| K[Row flagged red with reason; one-click 'exclude this account' or 'clamp to max']
  J -->|no| L[Owner confirms fan-out - Ctrl+Enter or Submit button]
  K --> L
  L --> M["Backend fans out N individual /v5/order/create calls, budgeted against per-UID rate limits"]
  M --> N[Each order tagged with trade_group_id; native exchange-side SL attached per account - MANDATORY, not optional]
  N --> O["WS order/execution streams confirm each leg independently"]
  O --> P{All legs acked?}
  P -->|partial failure| Q[Trade group shows mixed status: per-account success/fail rows, failed legs retryable individually]
  P -->|all success| R[Trade group status = Active, aggregated position view available]
  Q --> S[Owner reviews failed legs, retries or manually adjusts]
  R --> T[Journal auto-logs each leg as a linked trade record under the trade_group_id]
```

**Safety invariant:** every fanned-out order carries a native exchange-side SL regardless of any rule-engine stop configured later (owner decision, `24-owner-decisions.md` §3).

---

## 6. Chart trading — click-to-order, drag SL/TP

**Actor:** P1/P2. **Route:** R-101 (Terminal), triggers M-001.
**Screens:** SCR-030, SCR-040, SCR-060, SCR-064, SCR-076 (see `14-screens-catalogue.md`).

```mermaid
flowchart TD
  A[Chart focused, 1-click trading OFF by default] --> B{User action}
  B -->|Click price axis| C[Ctrl+Click = market order at current price]
  B -->|Shift+Click| D[Limit order at clicked price]
  C --> E{1-click trading armed?}
  D --> E
  E -->|no| F[Order ticket drawer opens pre-filled, requires explicit Submit/Ctrl+Enter]
  E -->|yes, armed via toggle with visible lock icon| G[Order fires immediately - toast confirmation with 3s undo-cancel window if still working]
  F --> H[Order sent to backend -> Bybit /v5/order/create]
  G --> H
  H --> I[Position opens; SL/TP handles appear as draggable horizontal lines on chart]
  I --> J{User drags SL line}
  J -->|drag| K[Live preview shows new SL price + resulting R-multiple/loss $ while dragging]
  K --> L[Release drag -> confirm micro-toast 'SL moved to X, click to confirm' auto-confirms after 2s or Esc to revert]
  L --> M["Backend: /v5/position/trading-stop update"]
  I --> N{User drags TP line}
  N --> K
```

**Accessibility parity:** every drag-based SL/TP adjustment has an exact keyboard equivalent (arrow keys nudge by tick with focus on the handle, Enter confirms) documented in `17-ux-diagrams.md` §8 hotkey map — canvas interactions are never mouse-only (T9 in `10-personas.md`).

---

## 7. DOM ladder trading

**Actor:** P1/P2. **Route:** R-101 pane (Heatmap+DOM Ladder view).
**Screens:** SCR-050, SCR-051, SCR-060, SCR-076 (see `14-screens-catalogue.md`).

```mermaid
flowchart TD
  A[DOM ladder pane focused] --> B{Click action}
  B -->|Click empty price cell| C[Places limit order at that price, size = active preset]
  B -->|Ctrl+Click| D[Market order]
  B -->|Drag own working order marker| E[Reprice via amend order]
  B -->|Right-click own order| F[Context menu: cancel, modify qty, convert to market]
  C --> G[Order appears on ladder as own-order marker, distinct glyph not just colour]
  D --> G
  G --> H[Fill arrives via WS order/execution]
  H --> I[Position row updates; ladder highlights current position price with a marker distinct from order markers]
  A -->|Esc| J[Cancel-all confirmation - M-006]
  A -->|+/-| K[Zoom price granularity]
```

---

## 8. Bracket / scaled order

**Actor:** P1/P2, M-003. **Route:** order ticket "Advanced" toggle.
**Screens:** SCR-060, SCR-069, SCR-065, SCR-064 (see `14-screens-catalogue.md`).

```mermaid
flowchart TD
  A[Order ticket - toggle Advanced] --> B[M-003: Bracket/Scaled builder]
  B --> C{Bracket or Scaled?}
  C -->|Bracket| D[Entry price/type, SL offset, 1-3 TP levels with % split, e.g. 50/30/20]
  C -->|Scaled| E["N orders across price range, distribution: equal/linear/geometric"]
  D --> F[Preview: total qty, per-leg qty, margin required, worst-case loss]
  E --> F
  F --> G{Confirm}
  G -->|Bracket| H["Backend: entry order + trading-stop TP/SL set atomically after entry fill confirmed via WS - not before, since fill isn't guaranteed"]
  G -->|Scaled| I["Backend places N individual limit orders client-side emulated (no native Bybit primitive), each linked by a scaled_order_group_id"]
  H --> J[Bracket appears as one logical entity in Positions & Orders, expandable to legs]
  I --> K[Scaled group shows fill progress bar - X of N legs filled]
  K --> L{User cancels remaining legs mid-fill?}
  L -->|yes| M[Cancel unfilled legs, keep filled portion as open position with native SL still attached to filled qty]
```

---

## 9. Emulated OCO / TWAP / iceberg lifecycle

**Actor:** P1/P2, M-004. **Route:** order ticket "Algo" toggle. This is the most safety-sensitive emulated-execution flow (per `09-execution-risk-tools.md` §2: none of these are native Bybit API primitives).
**Screens:** SCR-066, SCR-067, SCR-068, SCR-069, SCR-070 (see `14-screens-catalogue.md`).

```mermaid
sequenceDiagram
  participant U as User
  participant FE as Frontend
  participant BE as Backend OMS (algo executor)
  participant WS as Bybit private WS
  participant REST as Bybit REST

  U->>FE: Configure algo (OCO legs / TWAP slices / iceberg display+reserve qty)
  FE->>BE: POST algo config (algo_id, type, params)
  BE->>BE: Register algo state machine: PENDING
  alt OCO
    BE->>REST: Place order A (e.g. TP limit)
    BE->>REST: Place order B (e.g. SL stop)
    REST-->>BE: Both acked
    BE->>BE: state = ARMED (racing)
    WS-->>BE: order A filled
    BE->>REST: Cancel order B immediately
    BE->>BE: state = COMPLETED
    Note over BE: Race window risk: if both fill near-simultaneously (thin liquidity), backend reconciles via execution WS timestamps and treats first-confirmed fill as canonical, immediately cancels the other; a double-fill (both legs execute) is logged as a P1-severity incident and surfaced to the user via M-028 (Emulated-OCO reconciliation notice, `12-sitemap.md` §5), a modal deep-linkable at `?panel=oco-reconcile&groupId=` that shows both fills, net exposure, and a one-click "flatten to intended net position" action - this is a disclosed limitation of emulated OCO.
  else TWAP
    loop each slice, interval T
      BE->>REST: Place slice order (qty = total/N)
      REST-->>BE: Ack
      WS-->>BE: Fill or timeout
      BE->>FE: Update progress (slice i/N)
    end
    BE->>BE: state = COMPLETED when all slices done or user cancels remainder
  else Iceberg
    BE->>REST: Place visible-qty limit order
    WS-->>BE: Fill notification
    BE->>REST: Replace with next visible-qty chunk from reserve
    loop until reserve exhausted or cancelled
      WS-->>BE: Fill
      BE->>REST: Refresh next chunk
    end
  end
  BE->>FE: Live status: state machine diagram (PENDING/ARMED/PARTIAL/COMPLETED/CANCELLED/FAILED)
  U->>FE: Cancel algo at any time
  FE->>BE: Cancel request
  BE->>REST: Cancel all remaining child orders
  BE->>BE: state = CANCELLED
```

**Safety invariant:** the emulated algo runs server-side (backend OMS), **not** in the browser — if the Electron app is closed mid-TWAP/iceberg, the backend continues executing and the native SL (placed at position-open time, independent of the algo) still protects the position. A disconnected UI never leaves a position unprotected (T4 in `10-personas.md`).

---

## 10. Rule creation (form + node editor, shared IR)

**Actor:** M1 Rule author (P1 or P2 with `rules:author`). **Routes:** R-163 → R-161/R-162.
**Screens:** SCR-080, SCR-081, SCR-082, SCR-083, SCR-088, SCR-084, SCR-085 (see `14-screens-catalogue.md`).

```mermaid
flowchart TD
  A["/rules/new"] --> B{Start in form or graph?}
  B -->|Form| C["/rules/:id?mode=form"]
  B -->|Graph| D["/rules/:id/graph"]
  C --> E[Structured editor: scope account/symbol, trigger type, conditions AND/OR list, actions list]
  D --> F[Node-graph editor: drag trigger node -> condition nodes -> action nodes, wire connections]
  E --> G[Compile to Rule IR - JSON per 24-internal-schemas.md]
  F --> G
  G --> H{Switch editor mid-edit?}
  H -->|yes| I[Re-render other editor from same IR - round-trip verified, no data loss]
  I --> E
  I --> F
  G --> J[Save as Draft - simulate-only, not armed]
  J --> K[Optional: auto-backtest against recorder history for this symbol]
  K --> L{Sufficient history?}
  L -->|no| M[Show 'insufficient recorded history for backtest' empty state, not blocking save]
  L -->|yes| N[Show simulated fire count/outcomes over available window]
  J --> O[User clicks Arm]
  O --> P{Arming live? role check}
  P -->|Manager| Q[Step-up TOTP required, scoped to own accounts only]
  P -->|Owner| R[Step-up TOTP required]
  Q --> S{Conflicts with existing armed rule on same position?}
  R --> S
  S -->|yes| T[M-009 conflict resolver: show both rules, require explicit precedence order before arming]
  S -->|no| U[Rule state = ARMED]
  T --> U
```

**UX research:** [e36-rules-in-words.md](../design/research/e36-rules-in-words.md) (E36-D01; heuristic, pending owner approval; the route is `/rules/:id?mode=form` as drawn here against `14`'s `/rules/:ruleId/form`, with `form` proposed as the default editor — its C9 / Q7; the "conditions AND/OR list" is "all of" with one any-of level, or a flat "any of", its R3).

---

## 11. Rule firing & native SL backstop

**Actor:** system (rule engine), observed by P1/P2/P3. **Route:** R-164 (history), notifications.
**Screens:** SCR-087, SCR-086, SCR-014, SCR-063, SCR-073 (see `14-screens-catalogue.md`).

```mermaid
sequenceDiagram
  participant Engine as Rule Engine
  participant Data as Live feeds (price/CVD/OI/etc.)
  participant OMS as OMS
  participant Bybit as Bybit API
  participant U as User

  loop continuous evaluation
    Data->>Engine: tick/bar/indicator update
    Engine->>Engine: Evaluate conditions for all ARMED rules in scope
  end
  Engine->>Engine: Condition met for Rule X
  Engine->>OMS: Execute action (e.g. modify_stop_loss, move_to_breakeven, flatten_all_positions)
  OMS->>Bybit: REST call (trading-stop / order-cancel / order-create)
  Bybit-->>OMS: Ack
  OMS->>U: Notification (toast + optional push): "Rule 'Trail by 1.5 ATR' fired on BTCUSDT: SL moved to 61,200"
  OMS->>Engine: Log fire event to Rule history (R-164) and Journal (auto-tag)
  Note over OMS,Bybit: Independent of rule engine health, every position already carries a native exchange-side hard SL placed at entry. If the rule engine process, backend, or WS connection dies, the native SL remains resting on Bybit's matching engine and still protects the position - this is the backstop invariant, not a rule-engine feature.
  alt Rule engine crashes or backend disconnects
    Bybit->>Bybit: Native SL continues to rest on exchange book unaffected
    U->>U: Sees "Rule engine offline" banner + heartbeat-missed alert
  end
```

---

## 12. Journal review

**Actor:** P1 Owner (full), P2 Manager (own accounts), P3 Viewer (if granted). **Routes:** R-180 → R-181 → R-182; deep links to/from R-171 (Replay) via `?fromReplay=`/`?fromTrade=`.
**Screens:** SCR-093, SCR-094, SCR-095, SCR-096, SCR-097 (see `14-screens-catalogue.md`).

```mermaid
flowchart TD
  A["/journal - trade list"] --> B[Filter: account, symbol, date range, tag, R-multiple, win/loss]
  B --> C{Trades match filter?}
  C -->|no| D["Empty state: 'No trades recorded yet' or 'No trades match filter' - see 17-ux-diagrams.md §5"]
  C -->|yes| E[Row per closed trade: entry/exit price+time, realized PnL, R-multiple, tags]
  E --> F[Click a row -> "/journal/:tradeId" - R-181]
  F --> G[Trade detail: full timeline, MAE/MFE chart, linked orders/fills, SL/TP history, any rules that fired on this position]
  G --> H[User adds/edits tags and free-text note - M-019 Journal trade quick-note drawer, autosaves]
  G --> I{Want market context at the time of trade?}
  I -->|yes| J["Click 'Open in Replay' -> /replay/:sessionId?fromReplay=... pre-seeded at trade's entry timestamp - R-171"]
  J --> K[Replay loads with a marker at the trade's entry/exit; user scrubs surrounding context]
  K --> L["Click 'Back to trade' -> returns to /journal/:tradeId via fromReplay param"]
  G --> M{Export this trade or filtered set?}
  M -->|yes| N[M-025: Export journal/analytics - choose CSV/PDF, range - RBAC per persona ◑/granted]
  E --> O["Click 'Analytics' tab -> /journal/analytics - R-182"]
  O --> P[Dashboards: win rate, R-distribution, equity curve, tag breakdown, time-of-day heatmap]
  P --> Q{Sufficient closed-trade sample?}
  Q -->|no| R["Empty/insufficient-data state: 'Not enough closed trades for this view yet' - never a broken chart"]
  Q -->|yes| S[Rendered analytics, filterable by same dimensions as trade list]
```

**Notes**
- Journal entries are generated automatically on position close (no manual "create trade" step) from the OMS fill/position-close event stream; manual edits are limited to tags/notes, never to the recorded fill data itself (audit integrity).
- Viewer access to Journal/Analytics is granted per-account by the Owner (`10-personas.md` §7); ungranted accounts are simply absent from the Viewer's filter list, not shown-then-blocked.
- `M-019` (quick-note) and `M-025` (export) are the only modal/drawer surfaces in this flow; everything else is full-page routes.

---

## 13. Switch Demo ↔ Live with safeguards

**Actor:** P1/P2. **Route:** environment badge menu, M-005.
**Screens:** SCR-074, SCR-075, SCR-006 (see `14-screens-catalogue.md`).

```mermaid
flowchart TD
  A[Click environment badge, e.g. currently DEMO] --> B[M-005: Confirm switch to LIVE]
  B --> C[Modal requires typed confirmation: type account name or 'LIVE' exactly]
  C --> D{Manager?}
  D -->|yes| E{Owner has enabled Live for this account?}
  E -->|no| F[Block: 'Owner has not enabled Live trading for this account']
  E -->|yes| G[Step-up TOTP required]
  D -->|no, Owner| G
  G --> H{Code valid?}
  H -->|no| G
  H -->|yes| I[Switch committed]
  I --> J[Entire chrome re-themes to Live accent - persistent text badge, never colour-only]
  J --> K[Order ticket limits chip refreshes to this account's live risk caps]
  K --> L{Any working Demo orders/positions?}
  L -->|yes| M[Clearly partitioned: 'Demo positions' section remains visible but read-only while in Live mode - never merged with Live P&L]
  L -->|no| N[Normal Live terminal]
  A -->|switching Live to Demo| O[No typed confirm required - only a lightweight click-confirm, since Demo is the safe direction]
```

---

## 14. Recording a symbol & auto-record

**Actor:** P1 Owner (config), all personas (observe recording status). **Routes:** R-340 (Admin recorder config), watchlist context menu (M-023).
**Screens:** SCR-140, SCR-141, SCR-142, SCR-100, SCR-103, SCR-047 (see `14-screens-catalogue.md`).

```mermaid
flowchart TD
  A[Symbol has no recording - default state] --> B{Trigger}
  B -->|User opens a chart for this symbol| C[Auto-record starts silently, 'Recording' badge appears on chart header]
  B -->|User opens a position on this symbol| C
  B -->|User manually adds to recorded-symbols list, M-023| C
  C --> D[Recorder subscribes to publicTrade + orderbook.200 + kline WS for this symbol]
  D --> E[Ticks/L2/bars persisted to QuestDB hot tier]
  E --> F{Retention period elapsed - default 30 days}
  F -->|not pinned| G[Old data purged per retention policy]
  F -->|pinned by user| H[Retained indefinitely, shown with pin icon in /admin/recorder]
  A --> I{User closes chart AND no open position AND not manually listed}
  I -->|yes, after grace period| J[Auto-record stops; existing history retained per policy, just no new capture]
  I -->|no| C
  D --> K[Disk budget display in /admin/recorder: ~0.5-0.75 GB/day/symbol estimate, running total vs available disk]
```

**Empty-history state:** any view depending on recorded history (Profile composite mode, Replay, footprint before recording started) explicitly shows "No recorded history before <start timestamp> for this symbol" rather than a blank/broken chart — see `17-ux-diagrams.md` §6 empty-state matrix.

---

## 15. Replay session

**Actor:** P1/P2/P3. **Routes:** R-170 → R-171.
**Screens:** SCR-098, SCR-097, SCR-099 (see `14-screens-catalogue.md`).

```mermaid
flowchart TD
  A["/replay - session picker"] --> B[Select symbol]
  B --> C[Select date/time range]
  C --> D{Range within recorded history?}
  D -->|no, partially| E[Show available sub-range highlighted, rest greyed with 'not recorded' tooltip]
  D -->|fully available| F[Range confirmed]
  E --> F
  F --> G[Choose playback speed 0.5x-100x, or scrub]
  G --> H[Choose: simulated-order/paper-fill toggle on/off]
  H --> I[Choose which panes stay live during replay vs replay-only]
  I --> J["/replay/:sessionId loads - Terminal-like layout + transport bar"]
  J --> K{Playback control}
  K -->|Space| L[Play/pause]
  K -->|Left/Right| M[Step bar]
  K -->|Shift+Left/Right| N[Step tick]
  K -->|R| O[Jump to real-time, exits replay]
  J --> P{Simulated orders enabled?}
  P -->|yes| Q[User can place orders against replayed book - fills computed by paper matcher against recorded L2, clearly labeled 'REPLAY - not a real order']
  P -->|no| R[Read-only replay]
  J --> S[Bookmark markers - user can drop a marker at a timestamp, later reachable from Journal via fromReplay param]
```

---

## 16. WS disconnect recovery UX

**Actor:** system-triggered, all personas. **Trigger:** any WS channel (public market data, private order/position, or backend↔frontend WS) drops.
**Screens:** SCR-152, SCR-153, SCR-158, SCR-159, SCR-030 (see `14-screens-catalogue.md`).

```mermaid
flowchart TD
  A[WS connection healthy] --> B{Heartbeat/ping missed}
  B -->|1 missed| C[Status bar latency indicator turns amber, no interruption]
  B -->|disconnect detected| D[M-021 shown: 'Connection lost - reconnecting...' non-blocking banner, chart freezes last-known state with a visible 'STALE' watermark on price panes]
  D --> E[Backend attempts reconnect with exponential backoff]
  E --> F{Reconnected within 10s?}
  F -->|yes| G[Banner dismisses, resubscribe all topics, orderbook re-synced via fresh snapshot not delta-patched]
  F -->|no, still down at 10s| H[Escalate: OS-native notification fired even if window minimized]
  H --> I{Trading-capable view active - order ticket/DOM/rules armed}
  I -->|yes| J["Show explicit: 'Order entry unavailable - market data stale. Positions remain protected by native exchange-side SL.' Order ticket disabled, not hidden"]
  I -->|no| K[Read-only views continue showing last-known state with STALE watermark]
  J --> L{Backend private-WS specifically down - not just public}
  L -->|yes| M[Backend's own dead-man's-switch consideration: does NOT auto-cancel orders - Bybit-side DCP is opt-in per key, documented separately; app surfaces 'position protection relies on already-placed native SL, no new orders can be verified' ]
  F -->|yes eventually, after minutes| N[Full resync: REST reconciliation pass - positions/orders/wallet re-fetched to catch any missed WS events during the gap, diffed against last local state, discrepancies logged]
```

---

## 17. Alert creation & delivery

**Actor:** P1/P2/P3 (view/create), M-022. **Routes:** R-190/R-191.
**Screens:** SCR-090, SCR-091, SCR-092, SCR-014, SCR-115 (see `14-screens-catalogue.md`).

```mermaid
flowchart TD
  A["/alerts - New alert"] --> B[Reuses Rule Builder condition editor, minus execution actions]
  B --> C[Define condition: price cross, indicator threshold, CVD divergence, funding rate, etc.]
  C --> D[Choose delivery: in-app toast default on; push and email opt-in, configured in /settings/notifications]
  D --> E[Choose one-shot vs recurring]
  E --> F[Choose scope: this symbol only vs global]
  F --> G[Save - alert state = ACTIVE]
  G --> H{Condition evaluated continuously}
  H -->|met| I[Fire: in-app toast + M-011 notifications centre entry]
  I --> J{Push/email enabled?}
  J -->|yes| K[Delivered via configured channel, even if app window closed - OS notification for push]
  J -->|no| L[In-app only, visible next time app is focused]
  I --> M{One-shot?}
  M -->|yes| N[Alert auto-disables after firing, shown as 'Fired at <time>' in list]
  M -->|no, recurring| O[Remains active, subject to snooze/mute controls]
```

---

## 18. Key rotation

**Actor:** P4 Admin-hat. **Route:** R-322.
**Screens:** SCR-127, SCR-128, SCR-149 (see `14-screens-catalogue.md`).

```mermaid
flowchart TD
  A["/admin/keys/:keyId - Rotate"] --> B[Warn: rotating will invalidate old key immediately on save - no overlap period on Bybit side]
  B --> C[Generate new sub-API key on Bybit with identical permission set, same IP whitelist requirement]
  C --> D[Backend verifies new key: same permission-verification flow as flow #2 - withdrawal check, scope check, IP check]
  D --> E{Verified?}
  E -->|no| F[Abort rotation, old key remains active, show failure reason]
  E -->|yes| G[Step-up TOTP required to commit]
  G --> H[Commit: new key stored encrypted, old key revoked on Bybit, old key purged from local store]
  H --> I[Audit log: key rotated, old key id, new key id, timestamp, actor]
  I --> J{Any open orders/positions using old key's session at rotation moment?}
  J -->|yes| K[Brief reconciliation: re-establish WS auth with new key, REST re-fetch to confirm no orders orphaned]
  J -->|no| L[Rotation complete, key status = Active]
```

---

## 19. Error / edge flows (consolidated)

### 18.1 Order rejected by Bybit (e.g., rate limit 10018/10006, insufficient margin, invalid tick size)

```mermaid
flowchart TD
  A[Order submitted] --> B[REST ack received]
  B --> C{retCode == 0?}
  C -->|yes| D[Await WS order/execution for true state]
  C -->|no| E{Error class}
  E -->|10006 too many visits / 10018 rate limit| F[Show 'Rate limited - retry in Ns', auto-retry once with backoff if user hasn't cancelled]
  E -->|insufficient margin| G[Show computed max affordable qty, offer one-click adjust]
  E -->|invalid tick/lot size| H[Client-side should have prevented this - log as a defect if it reaches here; show corrected value from instruments-info]
  E -->|other/unknown| I[Show raw Bybit error code+message verbatim, plus 'contact support' - never swallow unknown errors silently]
```

### 18.2 Trade group partial failure (see also flow §5)

- Already covered in flow §5 steps J/K/Q — failed legs are individually retryable, never silently dropped, and the trade group's aggregate view always distinguishes per-leg status.

### 18.3 Exchange 5xx / maintenance

```mermaid
flowchart TD
  A[Bybit REST returns 5xx] --> B[Backend retries with backoff, max N attempts]
  B --> C{Success within budget?}
  C -->|yes| D[Continue normally, no user-visible interruption if under 2s]
  C -->|no| E[Surface: 'Bybit API unavailable - orders queued/blocked', positions still protected by resting native SL]
  E --> F[Backend polls Bybit status/health; auto-resumes when REST recovers]
```

### 18.4 Rule engine conflict (two rules, same position)

- Covered in flow §10 step S/T (M-009 conflict resolver) — arming is blocked until explicit precedence is set.

### 18.5 Recorder disk pressure

```mermaid
flowchart TD
  A[Disk usage approaches configured threshold, e.g. 90%] --> B[Owner-only notification: 'Recorder disk usage at 90% - review retention']
  B --> C{Owner action}
  C -->|reduce retention| D[Applies to non-pinned symbols going forward]
  C -->|prune manually| E[Admin recorder screen: per-symbol size shown, manual delete non-pinned data]
  C -->|no action| F[At hard limit e.g. 98%, recorder auto-stops new capture for lowest-priority unpinned symbols, never deletes pinned data, logs the auto-stop]
```

### 18.6 Session idle timeout / lock

```mermaid
flowchart TD
  A[No input for configured idle period] --> B["/locked shown - R-005"]
  B --> C[Password required to resume - not full re-login, session/WS subscriptions preserved server-side]
  C --> D{Correct password?}
  D -->|yes| E[Resume exactly where left off]
  D -->|no, N attempts| F[Full logout forced, redirect to /login]
```

### 18.7 Manager exceeds risk cap mid-session (daily loss lockout)

```mermaid
flowchart TD
  A[Manager's realized+unrealized loss crosses configured daily cap] --> B[Server-side enforcement fires immediately - independent of any UI state]
  B --> C[Auto-flatten all positions for that account per policy]
  C --> D[Order placement revoked for remainder of lockout period]
  D --> E["M-027 shown to manager: lockout notice, expiry time, 'contact Owner for override' path"]
  E --> F{Owner overrides?}
  F -->|yes, step-up required| G[Lockout lifted early, audit logged with reason]
  F -->|no| H[Lockout expires naturally at next UTC day boundary or configured window]
```

---

## 20. Kill switch (global panic)

**Actor:** P1 Owner only. **Route:** status bar, any Terminal route, M-018.
**Screens:** SCR-072, SCR-071, SCR-073, SCR-010 (see `14-screens-catalogue.md`).

```mermaid
flowchart TD
  A[Owner clicks global Kill Switch] --> B[M-018: confirm - single click, no typed confirmation since this is a safety action not a risk-increasing one]
  B --> C[Backend immediately: cancel all working orders across ALL accounts, flatten ALL open positions across ALL accounts]
  C --> D[Halt new order placement for ALL accounts owner + all managers]
  D --> E[All managers' terminals switch to read-only within 2s with explicit banner: 'Kill switch activated by Owner at <time>']
  E --> F[Audit log: kill switch activated, resulting actions per account, timestamps]
  F --> G{Owner action to resume}
  G -->|Resume trading, step-up required| H[Halt lifted per-account, individually re-enabled by owner - not a single blanket 'undo']
```

**Distinction from per-manager FREEZE (Risk Dashboard, flow implicit in `10-personas.md` §3 scenario 5):** FREEZE targets one manager/account; Kill Switch is global, cancels+flattens (not just freezes), and is Owner-only with no Manager equivalent.

---

## 21. Auth, session and onboarding — full chain (E09-D02)

**Actors:** all personas (unauthenticated → authenticated), P2/P3 for the invite path.
**Screens:** SCR-001, SCR-002, SCR-003, SCR-004, SCR-005, SCR-006, SCR-010, SCR-017, SCR-019
(`14-screens-catalogue.md`). Structure and states matrix owned by `docs/design/E09/E09-D02.md`; this
diagram is the merged, canonical state machine (adopted decisions AD-1..AD-6 from
`docs/design/research/e09-auth-mental-models.md`, structural decisions in E09-D02 §2).

```mermaid
flowchart TD
  L[SCR-001 Login: idle] -->|submit| Ls[submitting]
  Ls -->|401 generic| Le[error-generic] --> L
  Ls -->|5 failures/15min| Lr[rate-limited, countdown] -->|expires| L
  Ls -->|account.disabled| Ld[account-disabled: terminal, contact owner]
  Ls -->|network down| Lu[server-unreachable, Retry] --> L
  Ls -->|200 + mfaToken| T[SCR-002 TOTP: idle]

  T -->|submit code| Tv[verifying]
  Tv -->|invalid| Ti[invalid-code] --> T
  Tv -->|mfaToken expired| Tx[expired-challenge] --> L
  Tv -->|5th failure| Tl[locked-after-5: recovery link stays live]
  Tv -->|200, first login or forced| E3{needs enrolment or password change?}
  T -->|use recovery code| Tr[recovery-code-entry]
  Tr -->|valid, codes remain| E3
  Tr -->|valid, zero remain, no TOTP| Tlk["recovery-exhausted-lockout: terminal,\ncontact owner (SCR-002)"]
  Tl -->|recovery code path| Tr

  E3 -->|needs TOTP enrolment| S3[SCR-003 enrol: step1-scan]
  E3 -->|needs forced password change| S4[SCR-004: policy-shown]
  E3 -->|neither| SH[SCR-010 App Shell]

  S3 --> S3b[step2-confirm] -->|invalid| S3b
  S3b -->|valid| S3c[step3-codes-shown] -->|I saved them + continue| S3d[step3-completed] --> SH
  S3 -->|re-enrol trigger: owner reset or recovery consumed| S3re[re-enrol-variant] --> S3

  S4 -->|typing| S4t[typing] -->|reused/breached| S4e[server-reject] --> S4t
  S4t -->|valid + confirmed| S4s[success] --> SH

  SH -->|access token cannot refresh| M5[SCR-005 modal: default]
  M5 -->|order ticket open| M5o[expiry-during-order-entry:\nticket echoed read-only, WS paused not torn down]
  M5 -->|sign in again| SH
  M5 -->|sign out instead| L
  M5o -->|sign in again| SH

  SH -->|privileged action| M6[SCR-006 step-up: code-only or code+confirmation]
  M6 -->|active grace window, non-critical action| M6g[remaining-grace: countdown, Confirm] --> SH
  M6 -->|Live-enablement or kill-switch, grace ignored per AD-5| M6f[full dialog forced]
  M6 -->|valid| SH
  M6 -->|3 failures| M6d[three-strike-downgrade: action denied, toast] --> SH

  I[SCR-017 invite link] -->|valid| I1[accept invite] --> I2["SCR-004 embedded:\nset password"] --> I3["SCR-003 embedded:\nenrol TOTP"] --> I4[orientation card] --> SH
  I -->|expired| Ix[invite-expired: terminal, ask owner for new one]
  I -->|already used| Iu[invite-already-used: terminal, ask owner for new one]

  SH -.->|empty workspace / Settings-Help| CL[SCR-019 setup checklist: pending/done/blocked]
```

**Node resolution summary (no dead ends):** every terminal node above (`Ld`, `Tlk`, `Ix`, `Iu`) explicitly
names the owner as the unblock path per the ticket's acceptance criterion; every other leaf either loops
back to a live retry (`Le`→`L`, `Ti`→`T`, `Lu`→`L`, `S4e`→`S4t`, `S3b`→`S3b`) or reaches `SH` (the app
shell). Full per-state detail, the recovery-code-exhaustion frame, and the interruption-preservation
frame are specified in `docs/design/E09/E09-D02.md`.

---

## 22. Traceability

- All routes/modals referenced (`R-###`, `M-###`) are defined in `12-sitemap.md`.
- State machines referenced (order, rule, algo, connection) are formalized as state diagrams in `17-ux-diagrams.md` §4.
- Screen-level detail (states, hotkeys, a11y) for every screen touched by these flows is in `14-screens-catalogue.md`.
- Rule IR structure referenced in flow §10/§11 is defined in `24-internal-schemas.md`.
