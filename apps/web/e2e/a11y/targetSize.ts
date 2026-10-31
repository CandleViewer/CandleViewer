/**
 * WCAG 2.2 SC 2.5.8 Target Size (Minimum), E47-S05 (#1319, Gherkin "Targets meet the minimum or are
 * registered exceptions"). Pure geometry, no DOM: the Playwright check (`target-size.spec.ts`) feeds
 * it measured boxes, the unit tests feed it synthetic ones. The size is the token `--size-target-min`.
 *
 * A target passes when its box is at least 24 x 24 CSS px, or when a 24 px circle centred on its box
 * touches no other target's box and no other undersized target's circle (the spacing arm). An inline
 * target (a link inside a sentence) and a user-agent-controlled one are exempt by the standard and
 * arrive pre-tagged; anything else under 24 px needs an entry in the register
 * (`docs/qa/a11y/e47-target-size-exceptions.md`), which names its alternative.
 */
export const TARGET_MIN = 24;

export interface TargetBox {
  /** A stable name for the report: the screen-local selector or accessible name. */
  readonly id: string;
  readonly x: number;
  readonly y: number;
  readonly w: number;
  readonly h: number;
  /** Inline in a run of text, or user-agent controlled: exempt (2.5.8 exceptions). */
  readonly exempt?: "inline" | "user-agent";
}

export interface TargetViolation {
  readonly id: string;
  readonly w: number;
  readonly h: number;
  /** The id of the nearest neighbour that breaks the spacing arm. */
  readonly crowdedBy: string;
}

const small = (t: TargetBox): boolean => t.w < TARGET_MIN || t.h < TARGET_MIN;

/** Does the circle of radius `r` around (cx, cy) reach the box? */
function circleHitsBox(cx: number, cy: number, r: number, b: TargetBox): boolean {
  const dx = Math.max(b.x - cx, 0, cx - (b.x + b.w));
  const dy = Math.max(b.y - cy, 0, cy - (b.y + b.h));
  return dx * dx + dy * dy < r * r;
}

/** Targets under the minimum with no 24 px of clear space around them, in input order. */
export function targetViolations(targets: readonly TargetBox[]): TargetViolation[] {
  const r = TARGET_MIN / 2;
  const out: TargetViolation[] = [];
  for (const t of targets) {
    if (t.exempt !== undefined || !small(t)) continue;
    const cx = t.x + t.w / 2;
    const cy = t.y + t.h / 2;
    const crowd = targets.find((o) => {
      if (o === t) return false;
      if (!small(o)) return circleHitsBox(cx, cy, r, o);
      const d = Math.hypot(cx - (o.x + o.w / 2), cy - (o.y + o.h / 2));
      return d < TARGET_MIN; // two radius-12 circles intersect
    });
    if (crowd !== undefined) out.push({ id: t.id, w: t.w, h: t.h, crowdedBy: crowd.id });
  }
  return out;
}

export interface TargetException {
  readonly id: string;
  /** `*`, or the screen id (`R-203`). */
  readonly screen: string;
  /** A CSS selector the offending element matches. */
  readonly selector: string;
  readonly alternative: string;
}

/** Rows of the register's table: `| TS-01 | R-203 | \`selector\` | ... | alternative | ... |`. */
export function parseExceptionRegister(markdown: string): TargetException[] {
  const rows: TargetException[] = [];
  for (const line of markdown.split("\n")) {
    const cells = line.split("|").map((c) => c.trim());
    const id = /^TS-\d+$/u.exec(cells[1] ?? "")?.[0];
    if (id === undefined) continue;
    const selector = /^`(.+)`$/u.exec(cells[3] ?? "")?.[1];
    rows.push({
      id,
      screen: cells[2] ?? "",
      selector: selector ?? "",
      alternative: cells[6] ?? "",
    });
  }
  return rows;
}
