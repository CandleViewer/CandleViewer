import type { JSX } from "react";
import { Icon } from "@candleviewer/ui";
import type { Item, ItemState, StrengthWord } from "./policy";

/** W-6 and W-7: the words each item's state reads in its accessible name. */
export const STATE_WORDS: Readonly<Record<ItemState, string>> = {
  met: "met",
  "not-met": "not met",
  server: "checked when you submit",
};

/**
 * CMP-203 RequirementChecklist, the SCR-004 build (E09-D05 §4.2): every item laid out at mount, its
 * words with its state in its accessible name, the glyph and the weight beside them, never colour
 * alone. Not a live region (C-8): the host's one status node speaks the item that changed. A state
 * change swaps text and glyph only, so nothing shifts under the typing user.
 */
export function RequirementChecklist(props: {
  readonly id: string;
  readonly items: readonly Item[];
}): JSX.Element {
  return (
    <ul id={props.id} aria-label="Password requirements" style={{ margin: 0, paddingInline: 0 }}>
      {props.items.map((item) => {
        const met = item.state === "met";
        return (
          <li
            key={item.id}
            style={{
              listStyle: "none",
              fontWeight: met ? 600 : 400,
              color: met ? "var(--color-text-primary)" : "var(--color-text-secondary)",
            }}
          >
            <span
              style={{
                color: met ? "var(--color-status-success-strong)" : "var(--color-text-secondary)",
              }}
            >
              <Icon name={met ? "check" : "minus"} size="sm" />
            </span>{" "}
            {item.label}
            <span className={item.state === "server" ? undefined : "cv-visually-hidden"}>
              {item.state === "server"
                ? ` (${STATE_WORDS.server})`
                : `, ${STATE_WORDS[item.state]}`}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

const SEGMENTS: Readonly<Record<StrengthWord, number>> = { Weak: 1, Fair: 2, Strong: 3 };

/**
 * CMP-202 PasswordStrengthMeter, the SCR-004 build (E09-D05 §4.3): the word first, a bar beside it
 * whose segments fill by class flip. Advisory: it never gates the submit, never takes a status colour
 * or a check glyph, and never sits inside the checklist (R-3).
 */
export function PasswordStrengthMeter(props: {
  readonly id: string;
  readonly word: StrengthWord;
}): JSX.Element {
  const filled = SEGMENTS[props.word];
  return (
    <p id={props.id} style={{ margin: 0, color: "var(--color-text-primary)" }}>
      Strength: {props.word}{" "}
      <span aria-hidden="true" style={{ display: "inline-flex", gap: "2px" }}>
        {[1, 2, 3].map((n) => (
          <span
            key={n}
            data-filled={n <= filled}
            style={{
              display: "inline-block",
              inlineSize: "2rem",
              blockSize: "0.25rem",
              border: "1px solid var(--color-border-strong)",
              background:
                n <= filled ? "var(--color-text-secondary)" : "var(--color-border-strong)",
            }}
          />
        ))}
      </span>
    </p>
  );
}
