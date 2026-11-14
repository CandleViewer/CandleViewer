// E16-S03: SCR-141's copy against the merged deck (E16-D06 §20.1, `E16-D06-copy.json`) and the
// frozen row (viii) of E16-D06 §20.3; the T2 reason (vi) is `@candleviewer/ui`'s, checked here too.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { RBAC_REASONS } from "@candleviewer/ui";
import {
  RETENTION_DECK,
  RETENTION_PROPOSED,
  STREAM_WORDS,
  type RetentionDeckKey,
} from "../../../../src/features/recorder/retention/retentionCopy";

interface DeckRow {
  readonly parent: string;
  readonly string: string;
  readonly sources: Readonly<Record<string, string>>;
}
const DECK_JSON = resolve(
  import.meta.dirname,
  "../../../../../../docs/design/E16/E16-D06-copy.json",
);
const deck = (JSON.parse(readFileSync(DECK_JSON, "utf8")) as { strings: Record<string, DeckRow> })
  .strings;
const keys = Object.keys(RETENTION_DECK) as RetentionDeckKey[];
/**
 * The one D03 row whose string quotes another string (the history-start line it names): the deck's
 * tool cuts a row at every quote mark, so the deck holds that sentence in two parts around it.
 */
const QUOTED_INSIDE: Partial<Record<RetentionDeckKey, string>> = {
  "retention.effect": '"Older data was removed by the retention policy (<N> days)."',
};

describe("retention copy (E16-D03 §14)", () => {
  it.each(keys)("test_copy_%s_equals_the_deck", (key) => {
    const row = RETENTION_DECK[key].join(" · ");
    const inside = QUOTED_INSIDE[key];
    expect(inside === undefined ? row : row.replace(inside, " · ")).toBe(deck[key]?.string);
  });

  it("test_copy_carries_every_d03_row_but_the_t2_reason_the_ui_package_owns", () => {
    const wanted = Object.entries(deck)
      .filter(([key, row]) => row.parent === "D03" && key !== "rbac.view_as")
      .map(([key]) => key);
    expect([...keys].sort()).toEqual(wanted.sort());
    // E09-D09's key: SCR-141 names `RBAC_REASONS`' entry, and its words are the deck's (vi).
    expect(deck["rbac.view_as"]?.string.split(" · ")[0]).toBe(RBAC_REASONS["rbac.view_as"]);
  });

  it("test_copy_effect_line_is_its_parent_cell_verbatim", () => {
    const [effect] = RETENTION_DECK["retention.effect"];
    expect(deck["retention.effect"]?.sources["D03"]).toBe(`"${effect}"`);
  });

  it("test_copy_stream_words_pair_each_stream_kind_as_the_deck_does", () => {
    const cell = deck["retention.stream.*"]?.sources["D03"] ?? "";
    const pairs = Object.entries(STREAM_WORDS);
    expect(pairs).toHaveLength(8);
    for (const [stream, word] of pairs) expect(cell).toContain(`${stream} "${word}"`);
  });

  it("test_copy_proposed_words_are_no_deck_row_yet_and_name_no_data", () => {
    // PROPOSED for E16-D03's owner: once the deck carries a key, it moves into RETENTION_DECK.
    expect(Object.keys(RETENTION_PROPOSED)).toEqual(["retention.scope.unknown"]);
    for (const [key, [words = ""]] of Object.entries(RETENTION_PROPOSED)) {
      expect(deck[key], key).toBeUndefined();
      expect(words, key).not.toMatch(/[{}\d]|USDT/); // `{scope}`'s fill: no token, count or symbol
    }
  });

  it("test_copy_confirm_bodies_state_what_how_much_and_irreversible_frozen_viii", () => {
    for (const key of ["retention.confirm.body", "retention.confirm.body_now"] as const) {
      const [body = ""] = RETENTION_DECK[key];
      expect(body).toMatch(/^\{Stream\} for \{scope\} older than \{n\} days /); // what, which dates
      expect(body).toContain("{size clause}"); // how much
      expect(body).toContain("It cannot be undone."); // irreversible
    }
  });
});
