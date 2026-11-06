// E49-Q01 (#1335) S1: the GA regression pack's coverage map, built from the specs with nothing run
// (rules: `docs/qa/e49-ga-regression-pack.md`). A story id counts only in the shape US-<D>-<nnn>, so
// E17's `covers("C7", "D02-row-1")` cites nothing and fails nothing. `US-<D>-<nnn>#<Scenario>` cites
// one scenario: it never covers the story, which stays `partial` with a gaps row naming the rest.
import { readdirSync, readFileSync } from "node:fs";
import { join, relative, sep } from "node:path";

export const PACK_TAG = "@ga-regression";
export const AREAS =
  "auth trading multi-account rules alerts-journal replay admin state-matrix shell".split(" ");
/** E17's entry rule (`qa/plans/e17-regression-pack.md`): in after 10 green zero-retry nightlies. */
export const ENTRY_GREENS = 10;
/** The gap vocabulary: every gaps row's reason starts with one of these words. */
export const REASONS = ["unbuilt", "unmounted", "partial", "incidental", "below E2E", "parked"];
const STORY = /^US-[A-Z]+-\d{3}$/u;
const DECL = /^[ \t]*test(?:\.(\w+))?\(\s*(["`])((?:\\.|(?!\2)[^\\])*)\2/gmu;
/** The modifiers a titled `test.<m>("…")` declares a test with; `step` and `describe` are not tests. */
const PARK = new Set(["only", "skip", "fixme", "fail"]);

/** `stories` are whole-story citations; `scenarios` keep their fragment (`US-MKT-005#Reconnect`). */
export type PackTest = Readonly<{
  file: string;
  title: string;
  area: string;
  stories: string[];
  scenarios: string[];
}>;
export type Story = Readonly<{ id: string; priority: string; scenarios: readonly string[] }>;
type Parsed = { tests: PackTest[]; errors: string[] };
export type Gap = Readonly<{ stories: string[]; cells: string[] }>;

/** A title without its tags and story tokens: the name the nightly record keys on. */
export const bareTitle = (title: string): string => title.replace(/\s*@[\w-]+/gu, "").trim();

/** A cited id as the map reads it: the story shape after any `#fragment`, else nothing. */
export function storyId(raw: string): string | null {
  const id = raw.replace(/^@/u, "").split("#")[0]?.trim() ?? "";
  return STORY.test(id) ? id : null;
}

/** A scenario citation as the map keeps it, `US-<D>-<nnn>#<Scenario>`, else nothing. */
function scenarioOf(raw: string): string | null {
  const [head = "", ...rest] = raw.replace(/^@/u, "").split("#");
  const scenario = rest.join("#").trim();
  return storyId(head) !== null && scenario !== "" ? `${head.trim()}#${scenario}` : null;
}

function specFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const path = join(dir, e.name);
    if (e.isDirectory()) return e.name === "node_modules" ? [] : specFiles(path);
    return /\.(spec|real)\.ts$/u.test(e.name) ? [path] : [];
  });
}

const posix = (path: string): string => path.split(sep).join("/");

/** Every pack test under `dirs`, and each reason a tagged test cannot be in the pack. */
export function packTests(root: string, dirs: readonly string[]): Parsed {
  const tests: PackTest[] = [];
  const errors: string[] = [];
  const paths = dirs.flatMap((d) => specFiles(join(root, d))).map((p) => posix(relative(root, p)));
  for (const file of paths.sort()) {
    const path = join(root, file);
    const text = readFileSync(path, "utf8");
    const decls = [...text.matchAll(DECL)].filter((m) => m[1] !== "step");
    // A conditional skip, fixme or fail outside every test body (file level, or a describe before its
    // first test) parks the whole file: without brace matching, its reach is not known.
    const first = decls.find((m) => m[1] === undefined || PARK.has(m[1] ?? ""));
    const preambles = [
      text.slice(0, first?.index ?? text.length),
      ...decls
        .map((m, i) => (m[1] === "describe" ? text.slice(m.index, decls[i + 1]?.index) : ""))
        .filter((t) => t !== ""),
    ];
    const fileParked =
      /\.describe\.(fixme|skip)\(|test\.fixme\(true/u.test(text) ||
      preambles.some((t) => /\btest\.(skip|fixme|fail)\(/u.test(t));
    decls.forEach((m, i) => {
      const title = m[3] ?? "";
      if (!title.includes(PACK_TAG)) return;
      const span = text.slice(m.index, decls[i + 1]?.index ?? text.length);
      const where = `${file} › ${bareTitle(title)}`;
      const parked = m[1] !== undefined || /\.(fixme|skip|fail)\(|@flaky/u.test(span + title);
      if (parked || fileParked) {
        errors.push(`${where}: a fixme, skip, fail or @flaky test is never in the pack`);
      }
      const areas = [...title.matchAll(/@ga-area-([\w-]+)/gu)].map((a) => a[1] ?? "");
      const area = areas[0] ?? "";
      if (areas.length !== 1 || !AREAS.includes(area)) {
        errors.push(`${where}: needs exactly one @ga-area-<slug> of ${AREAS.join(", ")}`);
      }
      const cited = [
        ...[...title.matchAll(/@(US-[\w#-]+)/gu)].map((t) => t[1] ?? ""),
        ...[...span.matchAll(/\bcovers\(([^)]*)\)/gu)].flatMap((c) =>
          [...(c[1] ?? "").matchAll(/"([^"]*)"/gu)].map((s) => s[1] ?? ""),
        ),
      ];
      const whole = cited.filter((c) => !c.includes("#"));
      const stories = [...new Set(whole.map(storyId).filter((s): s is string => s !== null))];
      const scenarios = [...new Set(cited.map(scenarioOf).filter((s): s is string => s !== null))];
      tests.push({
        file,
        title: bareTitle(title),
        area,
        stories: stories.sort(),
        scenarios: scenarios.sort(),
      });
    });
  }
  return { tests, errors };
}

/** Every story heading of `11-user-stories.md`, its priority the LEADING token (`Must/Should` is Must). */
export function stories(markdown: string): Story[] {
  const heads = [...markdown.matchAll(/^#### (US-[A-Z]+-\d{3}) — .* · ([A-Za-z/]+)$/gmu)];
  return heads.map((m, i) => ({
    id: m[1] ?? "",
    priority: (m[2] ?? "").split("/")[0] ?? "",
    scenarios: [
      ...markdown.slice(m.index, heads[i + 1]?.index).matchAll(/^\s*Scenario: (.+?)\s*$/gmu),
    ].map((s) => s[1] ?? ""),
  }));
}

/** The rows of a markdown table whose first cell holds story ids. */
export const gaps = (markdown: string): Gap[] =>
  [...markdown.matchAll(/^\|\s*`US-.*$/gmu)].map(([line]) => {
    const cells = line.split(/\s*\|\s*/u).slice(1, -1);
    return { stories: [...(cells[0] ?? "").matchAll(/`([^`]+)`/gu)].map((s) => s[1] ?? ""), cells };
  });

export type NightlyRecord = Readonly<{ rows: Map<string, number>; errors: string[] }>;
const RECORD_HEAD = /^\|\s*Test\s*\|\s*Greens\s*\|$/u;
const RECORD_ROW = /^\|\s*`([^`]+ › [^`]+)`\s*\|\s*(\d+)\s*\|$/u;

/** The nightly record: `| <file> › <bare title> | <greens> |` rows under its header, any padding. */
export function greens(markdown: string): NightlyRecord {
  const lines = markdown.split("\n");
  const head = lines.findIndex((l) => RECORD_HEAD.test(l.trim()));
  const rows = new Map<string, number>();
  const errors: string[] = head < 0 ? ["nightly record: no `| Test | Greens |` table"] : [];
  for (const line of head < 0 ? [] : lines.slice(head + 2)) {
    if (!line.trim().startsWith("|")) break;
    const m = RECORD_ROW.exec(line.trim());
    if (m === null) errors.push(`nightly record row ${line.trim()}: not \`<spec> › <title>\` | n`);
    else if (rows.has(m[1] ?? "")) errors.push(`nightly record ${m[1] ?? ""}: in two rows`);
    else rows.set(m[1] ?? "", Number(m[2]));
  }
  return { rows, errors };
}

/** The story each scenario citation belongs to, with the scenarios cited. */
function scenarioMap(tests: readonly PackTest[]): Map<string, Set<string>> {
  const out = new Map<string, Set<string>>();
  for (const raw of tests.flatMap((t) => t.scenarios)) {
    const [id = "", ...rest] = raw.split("#");
    out.set(id, (out.get(id) ?? new Set<string>()).add(rest.join("#")));
  }
  return out;
}

/** Every reason the map is not whole: the five rules of the ruling's BQ-2, and the record's. */
export function mapErrors(
  tests: readonly PackTest[],
  all: readonly Story[],
  gapRows: readonly Gap[],
  record: ReadonlyMap<string, number>,
): string[] {
  const errors: string[] = [];
  const byId = new Map(all.map((s) => [s.id, s]));
  const covered = new Set(tests.flatMap((t) => t.stories));
  const cited = scenarioMap(tests);
  const gapped = new Map<string, number>();
  const reasonOf = new Map<string, string>();
  for (const row of gapRows) {
    const where = `gaps row ${row.stories.join(" ")}`;
    if (row.cells.length !== 5 || row.cells.slice(1).some((c) => c === "")) {
      errors.push(`${where}: needs reason, risk acceptance, by, date`);
    }
    if (!/^\d{4}-\d{2}-\d{2}$/u.test(row.cells[4] ?? "")) {
      errors.push(`${where}: the date is YYYY-MM-DD`);
    }
    const reason = row.cells[1] ?? "";
    if (reason !== "" && !REASONS.some((w) => reason.startsWith(`${w}:`))) {
      errors.push(`${where}: the reason starts with one of ${REASONS.join(", ")}, then a colon`);
    }
    for (const id of row.stories) {
      gapped.set(id, (gapped.get(id) ?? 0) + 1);
      reasonOf.set(id, reason);
    }
  }
  for (const id of [...covered, ...cited.keys(), ...gapped.keys()]) {
    if (storyId(id) === id && !byId.has(id)) errors.push(`${id}: not a story heading`);
    else if (storyId(id) !== id) errors.push(`${id}: not a story id`);
  }
  for (const [id, scenarios] of cited) {
    const known = byId.get(id)?.scenarios ?? [];
    for (const sc of scenarios) {
      if (byId.has(id) && !known.includes(sc)) errors.push(`${id}#${sc}: not a scenario of ${id}`);
    }
    if (covered.has(id) || !gapped.has(id)) continue;
    // Scenario citations never cover a story: its row says `partial` and names what is not cited.
    const missing = known.filter((sc) => !scenarios.has(sc) && !reasonOf.get(id)?.includes(sc));
    if (!reasonOf.get(id)?.startsWith("partial:") || missing.length > 0) {
      const names = known.filter((sc) => !scenarios.has(sc)).join(", ");
      errors.push(`${id}: cited by scenario only; its gaps row is partial and names ${names}`);
    }
  }
  for (const [id, n] of gapped) {
    if (covered.has(id)) errors.push(`${id}: in the gaps file but a pack test covers it`);
    if (n > 1) errors.push(`${id}: in ${n} gaps rows`);
  }
  for (const s of all) {
    if (s.priority === "Must" && !covered.has(s.id) && !gapped.has(s.id)) {
      errors.push(
        cited.has(s.id)
          ? `${s.id}: a Must story cited by scenario only, with no gaps row`
          : `${s.id}: a Must story neither covered nor in the gaps file`,
      );
    }
  }
  const keys = new Set(tests.map((t) => `${t.file} › ${t.title}`));
  for (const [key, n] of record) {
    if (!keys.has(key)) errors.push(`nightly record ${key}: no pack test has this name`);
    if (n > ENTRY_GREENS) errors.push(`nightly record ${key}: at most ${ENTRY_GREENS} greens`);
  }
  return errors;
}

/** A table formatted as prettier formats it (left-aligned, cells padded to the column). */
function table(rows: readonly (readonly string[])[]): string {
  const widths = (rows[0] ?? []).map((_, c) => Math.max(3, ...rows.map((r) => r[c]?.length ?? 0)));
  const line = (r: readonly string[]): string =>
    `| ${r.map((cell, c) => cell.padEnd(widths[c] ?? 0)).join(" | ")} |`;
  const [head, ...body] = rows;
  return [line(head ?? []), line(widths.map((w) => "-".repeat(w))), ...body.map(line)].join("\n");
}

/** The generated story-to-test table: one row per cited story, its spec files and their status. */
export function storyTable(
  tests: readonly PackTest[],
  all: readonly Story[],
  record: ReadonlyMap<string, number>,
): string {
  const priority = new Map(all.map((s) => [s.id, s.priority]));
  const covered = new Set(tests.flatMap((t) => t.stories));
  const cited = scenarioMap(tests);
  const ids = [...new Set([...covered, ...cited.keys()])].sort();
  const rows = ids.map((id) => {
    const mine = tests.filter(
      (t) => t.stories.includes(id) || t.scenarios.some((s) => s.startsWith(`${id}#`)),
    );
    const files = [...new Set(mine.map((t) => t.file))]
      .sort()
      .map((f) => `\`${f}\` (${mine.filter((t) => t.file === f).length})`)
      .join(", ");
    const n = mine.map((t) => record.get(`${t.file} › ${t.title}`) ?? 0);
    const inPack = n.filter((g) => g >= ENTRY_GREENS).length;
    const entry = inPack > 0 ? `in (${inPack})` : `candidate (${Math.max(...n)}/${ENTRY_GREENS})`;
    // A story cited only by scenarios keeps its fragments in the cell and is never covered.
    const story = covered.has(id) ? id : `${id}#${[...(cited.get(id) ?? [])].sort().join(", #")}`;
    const status = covered.has(id) ? entry : `partial, ${entry}`;
    const areas = [...new Set(mine.map((t) => t.area))].sort().join(", ");
    return [story, priority.get(id) ?? "", areas, files, status];
  });
  return table([["Story", "Priority", "Area", "Pack tests (by spec)", "Status"], ...rows]);
}
