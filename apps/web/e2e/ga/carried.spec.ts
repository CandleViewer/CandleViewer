import { test } from "./fixtures";

// E49-Q01 (#1335, BQ-01): the pack's carried flows. Each ticket-named flow whose surface is not
// shipped yet is a `test.fixme` stub here, tagged with its area and the Must stories it will
// cover, and a declared gap in docs/qa/ga-coverage-gaps.json (owning epic, checked surface, risk
// acceptance). The owner named in a title is the owning epic; a person is assigned when that
// epic's ticket is claimed. A stub covers nothing (tools/ga/coverage_map.py); when its surface
// lands, its owning ticket writes the body, drops `fixme` and deletes the gap entries, or the
// coverage check fails on the stale gap. No UI is invented here. Electron-only flows:
// apps/desktop/e2e/ga-carried.spec.ts.

// Primary trading flow (Demo)
test.fixme("@plan-GA-CARRIED chart load with footprint cells (E12, E18) @ga-regression @ga-area-primary @story-US-CHART-001 @story-US-FP-001", () => {});
test.fixme("@plan-GA-CARRIED DOM ladder interaction (E21) @ga-regression @ga-area-primary @story-US-DOM-001", () => {});
test.fixme("@plan-GA-CARRIED order ticket submit, amend, cancel in Demo (E30, E38) @ga-regression @ga-area-primary @story-US-ORD-001 @story-US-PAPER-001", () => {});
test.fixme("@plan-GA-CARRIED bracket attachment and the native-SL invariant (E32) @ga-regression @ga-area-primary @story-US-ALGO-001 @story-US-ORD-013", () => {});
test.fixme("@plan-GA-CARRIED position close (E29) @ga-regression @ga-area-primary @story-US-POS-003", () => {});
test.fixme("@plan-GA-CARRIED flatten-all with its confirm policy (E30, E47) @ga-regression @ga-area-primary @story-US-ORD-010 @story-US-SET-003", () => {});
// Multi-account
test.fixme("@plan-GA-CARRIED trade-group fan-out with per-account profiles (E28, E34) @ga-regression @ga-area-multi @story-US-PROF-001 @story-US-PROF-006", () => {});
test.fixme("@plan-GA-CARRIED fan-out through the rate-limit governor path (E34) @ga-regression @ga-area-multi @story-US-OBS-005", () => {});
// Rules
test.fixme("@plan-GA-CARRIED form and node editor round-trip (E36, E37) @ga-regression @ga-area-rules @story-US-RULE-004 @story-US-RULE-005 @story-US-RULE-006", () => {});
test.fixme("@plan-GA-CARRIED rule arm, trigger, disarm (E35) @ga-regression @ga-area-rules @story-US-RULE-010", () => {});
// Alerts and journal
test.fixme("@plan-GA-CARRIED alert creation and delivery (E40) @ga-regression @ga-area-alerts-journal @story-US-ALRT-001 @story-US-ALRT-005", () => {});
test.fixme("@plan-GA-CARRIED journal entry and export (E41) @ga-regression @ga-area-alerts-journal @story-US-JRN-001 @story-US-JRN-002", () => {});
// Replay: asserts golden outputs, never wall-clock (RSK-028)
test.fixme("@plan-GA-CARRIED replay seek, step, bookmark, exit to real time (E26) @ga-regression @ga-area-replay @story-US-RPL-001 @story-US-RPL-004", () => {});
// Admin, each at Owner, Manager and Viewer (the refusals ride admin-rbac.spec.ts today)
test.fixme("@plan-GA-CARRIED admin users at Owner, Manager, Viewer (E42) @ga-regression @ga-area-admin @story-US-ADMIN-001", () => {});
test.fixme("@plan-GA-CARRIED admin accounts and keys at Owner, Manager, Viewer (E27) @ga-regression @ga-area-admin @story-US-ACCT-002 @story-US-ACCT-006", () => {});
test.fixme("@plan-GA-CARRIED admin audit log at Owner, Manager, Viewer (E42) @ga-regression @ga-area-admin @story-US-ADMIN-008 @story-US-ADMIN-009", () => {});
test.fixme("@plan-GA-CARRIED admin feature flags at Owner, Manager, Viewer (E42) @ga-regression @ga-area-admin @story-US-ADMIN-007", () => {});
test.fixme("@plan-GA-CARRIED admin system health at Owner, Manager, Viewer (E42) @ga-regression @ga-area-admin @story-US-ADMIN-011", () => {});
// State matrix: E49-Q04 (#1362) contributes its scenarios as this tagged subset (BQ-11)
test.fixme("@plan-GA-CARRIED state-matrix subset (E49-Q04) @ga-regression @ga-area-state-matrix", () => {});
