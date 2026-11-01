// E16-S04: SCR-142's copy against the merged deck (E16-D06 §20.1, `E16-D06-copy.json`), and the
// import's served skip codes routed to E16-D04's sentences (BQ-4: the served names win).
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  IMPORT_SKIP_REASONS,
  STORAGE_DECK,
  type StorageDeckKey,
} from "../../../../src/features/recorder/storage/storageCopy";

interface DeckRow {
  readonly parent: string;
  readonly string: string;
}
const DECK_JSON = resolve(
  import.meta.dirname,
  "../../../../../../docs/design/E16/E16-D06-copy.json",
);
const deck = (JSON.parse(readFileSync(DECK_JSON, "utf8")) as { strings: Record<string, DeckRow> })
  .strings;
const keys = Object.keys(STORAGE_DECK) as StorageDeckKey[];

describe("storage copy (E16-D04 §14)", () => {
  it.each(keys)("test_copy_%s_equals_the_deck", (key) => {
    expect(STORAGE_DECK[key].join(" · ")).toBe(deck[key]?.string);
  });

  it("test_copy_carries_every_d04_row_but_the_purge_and_compact_rows_scr140_carries", () => {
    const wanted = Object.entries(deck)
      .filter(([key, row]) => row.parent === "D04" && !/^storage\.(purge|compact)\./.test(key))
      .map(([key]) => key);
    expect([...keys].sort()).toEqual(wanted.sort());
  });

  it("test_copy_import_skip_codes_route_to_their_deck_sentence_or_none", () => {
    expect(IMPORT_SKIP_REASONS).toEqual({
      import_checksum_failed: "storage.import.reason.checksum",
      import_parse_failed: "storage.import.reason.parse",
      import_download_failed: "storage.import.reason.download",
      import_file_not_found: null,
      import_file_too_large: null,
    });
    for (const key of Object.values(IMPORT_SKIP_REASONS)) {
      if (key !== null) expect(keys).toContain(key);
    }
  });
});
