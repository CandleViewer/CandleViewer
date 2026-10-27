import type { JSX } from "react";

export type ConfidenceLevel = "low" | "medium" | "high";

const FILLED: Readonly<Record<ConfidenceLevel, number>> = { low: 1, medium: 2, high: 3 };
const WORD: Readonly<Record<ConfidenceLevel, string>> = {
  low: "Low",
  medium: "Medium",
  high: "High",
};

export interface ConfidenceDotsProps {
  level: ConfidenceLevel;
  /**
   * The visible text, e.g. a numeric confidence ("72 %, medium confidence"). It must name the level (E17;
   * E25-D05 §9): an override without a level word gets ", {level} confidence" appended, and one that
   * names a different level is replaced by "{Level} confidence" (with a development warning).
   */
  label?: string;
}

const LEVELS: readonly ConfidenceLevel[] = ["low", "medium", "high"];

/** The level words in `text`, as whole words: "high-water" or "highly" name no level. */
const levelsNamed = (text: string): Set<ConfidenceLevel> => {
  const found = new Set<ConfidenceLevel>();
  for (const m of text.matchAll(/(?<![\w-])(low|medium|high)(?![\w-])/gi)) {
    found.add((m[1] ?? "").toLowerCase() as ConfidenceLevel);
  }
  return found;
};

/** The label the indicator shows: "{Level} confidence", or the override, which always names the level. */
export function confidenceLabel(level: ConfidenceLevel, label?: string): string {
  const fallback = `${WORD[level]} confidence`;
  const text = label?.trim() ?? "";
  if (text === "") return fallback;
  const named = levelsNamed(text);
  if (LEVELS.some((other) => other !== level && named.has(other))) {
    if (import.meta.env?.DEV) {
      console.warn(
        `ConfidenceDots: the label "${text}" names another level than "${level}"; showing "${fallback}"`,
      );
    }
    return fallback;
  }
  return named.has(level) ? text : `${text}, ${level} confidence`;
}

/**
 * CMP-032: a static low / medium / high confidence indicator. One info tone (E17): the level is the
 * filled-dot count and the text, never the hue. The dots are `aria-hidden`; the visible label is the
 * accessible text, plain and never a live region. Not focusable.
 */
export function ConfidenceDots({ level, label }: ConfidenceDotsProps): JSX.Element {
  const filled = FILLED[level];
  return (
    <span className="cv-confidence" data-cmp="CMP-032" data-level={level}>
      <span className="cv-confidence__dots" aria-hidden="true">
        {[0, 1, 2].map((i) => (
          <span key={i} className="cv-confidence__dot" data-filled={i < filled ? "" : undefined} />
        ))}
      </span>
      <span className="cv-confidence__label">{confidenceLabel(level, label)}</span>
    </span>
  );
}
