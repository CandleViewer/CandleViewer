#!/usr/bin/env node
// E40-S02 (#1130, BQ-5): compiles the ONE critical-override constant
// (packages/protocol/notification-overrides.json; E40-D01 section 5, E40-D02 section 6.2) into
//   - src/generated/notificationOverrides/index.ts                     (TS export)
//   - services/api/candleviewer/alerts/_generated/notification_overrides.py (Python twin)
// so the server, the settings UI and the tests read one list and never re-declare it. Every
// reference (category, channel, id) is checked; any mismatch aborts generation. Deterministic.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import prettier from "prettier";

const __dirname = dirname(fileURLToPath(import.meta.url));
const pkgRoot = join(__dirname, "..");
const repoRoot = join(pkgRoot, "..", "..");
const sourcePath = join(pkgRoot, "notification-overrides.json");
const tsOut = join(pkgRoot, "src", "generated", "notificationOverrides", "index.ts");
const pyDir = join(repoRoot, "services", "api", "candleviewer", "alerts", "_generated");
const pyOut = join(pyDir, "notification_overrides.py");
const pyInit = join(pyDir, "__init__.py");

const TOASTS = new Set(["toast", "banner"]);
const AUDIENCES = new Set(["every_role", "owner"]);
const TONES = new Set(["alert", "urgent", "reject", "critical"]);

function fail(msg) {
  throw new Error(`notification-overrides.json: ${msg}`);
}

function check(doc) {
  const cats = new Set(doc.categories);
  const chans = new Set(doc.channels);
  if (doc.version !== 1) fail(`unknown version ${doc.version}`);
  if (doc.user_alerts_override !== false) fail("user alerts never override (BQ-5)");
  if (!TONES.has(doc.override_tone)) fail(`unknown tone ${doc.override_tone}`);
  for (const c of doc.override_channels) if (!chans.has(c)) fail(`unknown channel ${c}`);
  const cells = new Set();
  for (const { category, channel } of doc.locked_cells) {
    if (!cats.has(category)) fail(`locked cell: unknown category ${category}`);
    if (!chans.has(channel)) fail(`locked cell: unknown channel ${channel}`);
    const key = `${category}.${channel}`;
    if (cells.has(key)) fail(`duplicate locked cell ${key}`);
    cells.add(key);
  }
  const ids = new Set();
  for (const o of doc.overrides) {
    if (!/^CO-[0-9]{1,2}$/.test(o.id) || ids.has(o.id)) fail(`bad or duplicate id ${o.id}`);
    ids.add(o.id);
    if (!cats.has(o.category)) fail(`${o.id}: unknown category ${o.category}`);
    if (!TOASTS.has(o.toast)) fail(`${o.id}: unknown toast form ${o.toast}`);
    if (!AUDIENCES.has(o.audience)) fail(`${o.id}: unknown audience ${o.audience}`);
    if (typeof o.label !== "string" || !o.label) fail(`${o.id}: no label`);
  }
  return doc;
}

const str = (v) => JSON.stringify(v);
const pyTuple = (xs) => `(${xs.map(str).join(", ")}${xs.length === 1 ? "," : ""})`;

function renderTs(d) {
  const lines = [
    "// ==========================================================================",
    "// GENERATED FILE — DO NOT EDIT BY HAND.",
    "// Regenerate with `pnpm --filter @candleviewer/protocol generate`.",
    "// Source: packages/protocol/notification-overrides.json (E40-D01 §5, E40-D02 §6.2)",
    "// via scripts/generate-notification-overrides.mjs. The Python twin is",
    "// services/api/candleviewer/alerts/_generated/notification_overrides.py.",
    "// ==========================================================================",
    "/* eslint-disable */",
    `export const NOTIFICATION_OVERRIDES_VERSION = ${d.version} as const;`,
    `export const NOTIFICATION_OVERRIDES_STATUS = ${str(d.status)} as const;`,
    `export const USER_ALERTS_OVERRIDE = ${d.user_alerts_override} as const;`,
    `export const NOTIFICATION_CATEGORIES = ${str(d.categories)} as const;`,
    `export type NotificationCategory = (typeof NOTIFICATION_CATEGORIES)[number];`,
    `export const NOTIFICATION_CHANNELS = ${str(d.channels)} as const;`,
    `export type NotificationChannel = (typeof NOTIFICATION_CHANNELS)[number];`,
    `export const LOCKED_CELLS = ${str(d.locked_cells)} as const;`,
    `export const CRITICAL_OVERRIDES = ${str(d.overrides)} as const;`,
    `export type CriticalOverrideId = (typeof CRITICAL_OVERRIDES)[number]["id"];`,
    `export const OVERRIDE_CHANNELS = ${str(d.override_channels)} as const;`,
    `export const OVERRIDE_TONE = ${str(d.override_tone)} as const;`,
    "",
  ];
  return lines.join("\n");
}

function renderPy(d) {
  const out = [
    '"""GENERATED FILE - DO NOT EDIT BY HAND.',
    "",
    "Generator: packages/protocol/scripts/generate-notification-overrides.mjs (E40-S02, #1130).",
    "Source: packages/protocol/notification-overrides.json (E40-D01 section 5, E40-D02 section 6.2).",
    "Run `pnpm --filter @candleviewer/protocol generate`.",
    '"""',
    "",
    "from __future__ import annotations",
    "",
    "from typing import Final, NamedTuple",
    "",
    "",
    "class Override(NamedTuple):",
    "    id: str",
    "    label: str",
    "    category: str",
    "    toast: str",
    "    audience: str",
    "",
    "",
    `VERSION: Final = ${d.version}`,
    `STATUS: Final = ${str(d.status)}`,
    `USER_ALERTS_OVERRIDE: Final = ${d.user_alerts_override ? "True" : "False"}`,
    `CATEGORIES: Final[tuple[str, ...]] = ${pyTuple(d.categories)}`,
    `CHANNELS: Final[tuple[str, ...]] = ${pyTuple(d.channels)}`,
    "LOCKED_CELLS: Final[frozenset[tuple[str, str]]] = frozenset(",
    "    {",
    ...d.locked_cells.map((c) => `        (${str(c.category)}, ${str(c.channel)}),`),
    "    }",
    ")",
    "OVERRIDES: Final[tuple[Override, ...]] = (",
    ...d.overrides.map(
      (o) =>
        `    Override(${str(o.id)}, ${str(o.label)}, ${str(o.category)}, ${str(o.toast)}, ${str(o.audience)}),`,
    ),
    ")",
    `OVERRIDE_CHANNELS: Final[tuple[str, ...]] = ${pyTuple(d.override_channels)}`,
    `OVERRIDE_TONE: Final = ${str(d.override_tone)}`,
    "",
  ];
  return out.join("\n");
}

async function main() {
  const doc = check(JSON.parse(readFileSync(sourcePath, "utf8")));
  mkdirSync(dirname(tsOut), { recursive: true });
  mkdirSync(pyDir, { recursive: true });
  const config = (await prettier.resolveConfig(tsOut)) ?? {};
  writeFileSync(
    tsOut,
    await prettier.format(renderTs(doc), { ...config, filepath: tsOut }),
    "utf8",
  );
  writeFileSync(pyOut, renderPy(doc), "utf8");
  writeFileSync(
    pyInit,
    '"""GENERATED by packages/protocol/scripts/generate-notification-overrides.mjs."""\n',
    "utf8",
  );
  console.log(`[generate-notification-overrides] wrote ${tsOut}, ${pyOut} and ${pyInit}.`);
}

await main();
