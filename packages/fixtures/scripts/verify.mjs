// Redaction gate for packages/fixtures (E02-T03 placeholder; real fixtures
// land in E08). Fails if any file under raw/, golden/, bybit/ or accounts/
// looks like it contains a credential (API key, signature, PEM block, bearer
// token); accounts/ also gets the bare key-shape check and the pack checks,
// the comparison with the E27 test plan's section 9.3 table included (E27-Q01).
// This is the control named in the ticket's Security notes for the
// "recorded fixture leaks credentials" threat (E02-X01).
// CI runs it through the package `lint` script (ESLint, this script, then the Vitest suite):
// the js lane's lint job schedules this package whenever a file in it changes.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, relative, resolve } from "node:path";
import { PLAN_FILE, PLAN_SCENARIOS, checkPack, findKeyShapedTokens } from "./accounts-pack.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const packageRoot = join(__dirname, "..");
// E08-T05: `bybit/` is the shared recorded corpus (packages/fixtures/bybit/<date>/).
// E27-Q01: `accounts/` is the accounts and key-vault fault-injection pack.
const DATA_DIRS = ["raw", "golden", "bybit", "accounts"];
const PACK_DIR = "accounts";
export const SCAN_DIRS = DATA_DIRS.map((d) => join(packageRoot, d));
// E27-Q01: a real Bybit key or secret is a bare 18-20 or 36 character alphanumeric token. The
// pack's ids are hyphenated by rule, so this extra shape check runs where the rule holds.
export const KEY_SHAPE_DIRS = [join(packageRoot, PACK_DIR)];

const SECRET_PATTERNS = [
  { name: "PEM private key block", re: /-----BEGIN [A-Z ]*PRIVATE KEY-----/ },
  { name: "bearer token", re: /Bearer\s+[A-Za-z0-9._-]{20,}/ },
  {
    name: "Bybit-style api key/secret field",
    re: /"(api[_-]?key|api[_-]?secret|sign|signature)"\s*:\s*"[^"]{8,}"/i,
  },
  {
    name: "generic long hex/base64 secret-shaped field",
    re: /"(secret|token|password)"\s*:\s*"[A-Za-z0-9+/=_-]{16,}"/i,
  },
  {
    // E08-X03: Bybit v5 auth headers, captured verbatim by a recorder that
    // did not redact them before the fixture was committed.
    name: "Bybit X-BAPI-* auth header",
    re: /X-BAPI-(API-KEY|SIGN)["']?\s*[:=]\s*["']?[A-Za-z0-9]{16,}/i,
  },
];

export function listFiles(dir) {
  let stat;
  try {
    stat = statSync(dir);
  } catch {
    return [];
  }
  if (!stat.isDirectory()) return [];
  const out = [];
  for (const entry of readdirSync(dir)) {
    if (entry === ".gitkeep") continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...listFiles(full));
    } else {
      out.push(full);
    }
  }
  return out;
}

export function scanForSecrets(files, readFile = (f) => readFileSync(f, "utf8")) {
  const findings = [];
  for (const file of files) {
    const content = readFile(file);
    for (const pattern of SECRET_PATTERNS) {
      if (pattern.re.test(content)) {
        findings.push({ file, pattern: pattern.name });
      }
    }
  }
  return findings;
}

/** Bare key- or secret-shaped tokens; the finding names the shape and position, never the token. */
export function scanForKeyShapes(files, readFile = (f) => readFileSync(f, "utf8")) {
  const findings = [];
  for (const file of files) {
    for (const hit of findKeyShapedTokens(readFile(file))) {
      findings.push({ file, pattern: `bare ${hit.shape}-shaped token at offset ${hit.index}` });
    }
  }
  return findings;
}

/**
 * Scans the given directories for secret-shaped content, plus the bare key-shape check over
 * `keyShapeDirs`, and returns the findings without exiting the process (CLI and tests).
 */
export function verifyDirectories(dirs, keyShapeDirs = []) {
  const files = dirs.flatMap(listFiles);
  const findings = [...scanForSecrets(files), ...scanForKeyShapes(keyShapeDirs.flatMap(listFiles))];
  return { files, findings };
}

function packProblems(dir, planFile) {
  let plan;
  try {
    plan = readFileSync(planFile, "utf8");
  } catch (error) {
    return [`plan: the test plan cannot be read (${error.code ?? error.name})`];
  }
  try {
    return checkPack(dir, { expectedScenarios: PLAN_SCENARIOS, plan });
  } catch (error) {
    return [`the pack cannot be read (${error.code ?? error.name})`];
  }
}

/**
 * Every finding for the package at `root`: the redaction gate over the data directories, the
 * bare key-shape rule and the pack checks over accounts/, against the test plan at `planFile`.
 * Returns instead of exiting (tests).
 */
export function runVerify(root = packageRoot, planFile = PLAN_FILE) {
  const pack = join(root, PACK_DIR);
  const { files, findings } = verifyDirectories(
    DATA_DIRS.map((d) => join(root, d)),
    [pack],
  );
  return { files, findings, packProblems: packProblems(pack, planFile) };
}

function main(root, planFile) {
  const { files, findings, packProblems: problems } = runVerify(root, planFile);
  const lines = [
    ...findings.map((f) => `  - ${relative(root, f.file)}: matched "${f.pattern}"`),
    ...problems.map((p) => `  - ${PACK_DIR}/${p}`),
  ];
  if (lines.length > 0) {
    console.error(
      "[fixtures-verify] FAILED — possible credential leak(s) or accounts pack problem(s):\n" +
        lines.join("\n"),
    );
    process.exit(1);
  }
  console.log(
    `[fixtures-verify] OK (${files.length} file(s) scanned, no matches; ` +
      `accounts pack sound, ${PLAN_SCENARIOS.length} scenarios matching the test plan).`,
  );
}

// Only run when executed directly (not when imported by tests importing
// `scanForSecrets`), so the test suite can exercise the pure function
// without triggering `process.exit`. Optional arguments name another package
// root and another test plan (the tests' planted copies); the defaults are this
// package and qa/plans/e27-accounts-test-plan.md.
const isMain = process.argv[1] && import.meta.url === new URL(process.argv[1], "file://").href;
if (isMain) {
  const [root, planFile] = process.argv.slice(2);
  main(root ? resolve(root) : packageRoot, planFile ? resolve(planFile) : PLAN_FILE);
}
