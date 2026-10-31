// E16-S01 slice 3: SCR-140's copy against the merged deck (E16-D06 §20.1, `E16-D06-copy.json`) and
// the frozen rows (vi) and (viii) of E16-D06 §20.3.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { DECK, TEXT, fill, type DeckKey } from "../../../src/features/recorder/copy";
import { formatDuration } from "../../../src/features/recorder/model";

type DeckRow = { readonly parent: string; readonly string: string; readonly status: string };
const DECK_JSON = resolve(import.meta.dirname, "../../../../../docs/design/E16/E16-D06-copy.json");
const deck = (JSON.parse(readFileSync(DECK_JSON, "utf8")) as { strings: Record<string, DeckRow> })
  .strings;
const keys = Object.keys(DECK) as DeckKey[];

describe("recorder copy", () => {
  it.each(keys)("test_copy_%s_equals_the_deck", (key) => {
    expect(DECK[key].join(" · ")).toBe(deck[key]?.string);
  });

  it("test_copy_carries_every_d02_and_purge_compact_row_of_the_deck", () => {
    const wanted = Object.entries(deck)
      .filter(([k, v]) => v.parent === "D02" || /^storage\.(purge|compact)\./.test(k))
      .map(([k]) => k);
    expect([...keys].sort()).toEqual(wanted.sort());
  });

  it("test_copy_t2_reasons_are_one_sentence_naming_no_data_frozen_vi", () => {
    const reasons = keys.filter((k) => k.startsWith("recorder."));
    expect(reasons).toHaveLength(5);
    for (const key of reasons) {
      const [text = ""] = DECK[key];
      expect(deck[key]?.status, key).toBe("PROPOSED");
      expect(text.length, key).toBeLessThanOrEqual(60);
      expect(text, key).toMatch(/^[^.]+\.$/);
      // the only token is the policy's linger; no symbol, count or size
      expect(text.replace("{grace}", ""), key).not.toMatch(/[{}\d]|USDT/);
    }
  });

  it("test_copy_purge_body_states_what_how_much_and_irreversible_frozen_viii", () => {
    const [body] = DECK["storage.purge.body"];
    expect(body).toContain("about {size} recorded from {from} to {to} from QuestDB and Parquet");
    expect(body).toContain("It cannot be undone");
  });

  it("test_copy_durations_render_as_the_deck_writes_them", () => {
    expect([60, 1800, 5400].map(formatDuration)).toEqual([...DECK["d02.8.r01"]]);
    expect([90, 3600, 3660, 45].map(formatDuration)).toEqual(["90 s", "1 h", "1 h 1 min", "45 s"]);
  });

  it("test_copy_disk_unavailable_is_the_decks_storage_unavailable_a12", () => {
    expect(TEXT.diskUnavailable).toBe(deck["storage.unavailable"]?.string);
  });

  it("test_copy_fill_replaces_every_literal_token", () => {
    expect(
      fill(DECK["storage.purge.failed"][0], { "{symbol}": "ADAUSDT", "`<code>`": "io_error" }),
    ).toBe(
      "Purge of ADAUSDT failed (io_error). Some data may already be deleted: check ADAUSDT's size and gaps.",
    );
    expect(fill(DECK["storage.purge.title"][0], { "{symbol}": "ETHUSDT" })).toBe(
      DECK["storage.purge.title"][1],
    );
    expect(
      fill(TEXT.incident, {
        "{count}": "1 204",
        "{symbol}": "ETHUSDT",
        "{from}": "10:14:03",
        "{to}": "10:14:41",
      }),
    ).toBe(
      "Incident: 1 204 messages were dropped on ETHUSDT between 10:14:03 and 10:14:41 UTC. The lost interval is recorded as a gap; charts and replay show it as a gap.",
    );
  });

  it("test_copy_fill_puts_a_value_in_literally_never_as_a_replacement_pattern", () => {
    expect(fill("Purge {symbol} data", { "{symbol}": "A$&B$1$$" })).toBe("Purge A$&B$1$$ data");
  });
});
