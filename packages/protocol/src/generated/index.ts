// ==========================================================================
// GENERATED FILE — DO NOT EDIT BY HAND.
// Regenerate with `pnpm --filter @candleviewer/protocol generate`. Hand
// edits are rejected by the header-guard lint
// (packages/protocol/scripts/check-generated-guard.mjs) and by
// `linguist-generated` in .gitattributes.
//
// Barrel for the generated surfaces, written by scripts/generate-barrel.mjs:
//  - ./rest   — TS types for docs/plan/22-api-openapi.yaml (via openapi-typescript)
//  - ./ws     — TS types for docs/plan/23-ws-protocol.md §13-15 (via ws-schema.json)
//  - ./policy — enum-value tables mirroring services/api/candleviewer/
//               exchange/policy.py (tools/gen/export_instrument_policy_rules.py)
//  - ./bars   — bar domain model mirroring services/api/candleviewer/bars/
//               models.py (scripts/generate-bar-types.mjs)
// ==========================================================================
export * as rest from "./rest/index.js";
export * as ws from "./ws/index.js";
export * as policy from "./policy/index.js";
export * as bars from "./bars/index.js";
