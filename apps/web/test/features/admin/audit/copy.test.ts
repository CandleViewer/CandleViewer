/**
 * E42-S04 (#1135): SCR-135 and SCR-136's words come from E42-D04 §14 by key (D30; "a screen cites a
 * key, never its own string", D09:85). Each keyed string below is read back out of the deck, so a
 * copy edit in one place and not the other fails here; the strings marked PROPOSED must not be the
 * deck's, so their marking stays true. Fills are formatted the way §1 writes them.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  AUDIT_COPY as COPY,
  num,
  range,
  size,
  utc,
} from "../../../../src/features/admin/audit/copy";

const DECK = readFileSync(
  resolve(import.meta.dirname, "../../../../../../docs/design/E42/E42-D04.md"),
  "utf8",
);
const D09 = readFileSync(
  resolve(import.meta.dirname, "../../../../../../docs/design/E09/E09-D09.md"),
  "utf8",
);
/** §14's row for `prefix`, its padding folded. */
const row = (prefix: string): string => {
  const line = DECK.split("\n").find((l) => l.startsWith(`| \`${prefix}\``));
  if (line === undefined) throw new Error(`D04 §14 has no ${prefix} row`);
  return line.replace(/ {2,}/g, " ");
};

describe("the deck's strings, by their names (D04 §14)", () => {
  it.each([
    ["audit.*", COPY.audit.appendOnly],
    ["audit.*", COPY.audit.marker],
    ["audit.*", COPY.audit.caption],
    ["audit.*", COPY.audit.slow],
    ["audit.*", COPY.audit.noMatch],
    ["audit.*", COPY.audit.ownOnly],
    ["audit.*", COPY.audit.ownNoMatch],
    ["audit.*", COPY.audit.ownFilter],
    ["audit.*", COPY.audit.envPage("{ENV}").replace("{ENV}".toUpperCase(), "{ENV}")],
    ["audit.*", COPY.audit.newN(7, false).replace("7", "{n}")],
    ["audit.*", COPY.audit.newN(1, false)],
    ["audit.*", COPY.audit.newN(200, true)],
    ["audit.*", COPY.audit.newLoaded(7).replace("7", "{n}")],
    ["audit.*", COPY.audit.count(7).replace("7", "{n}")],
    ["audit.*", COPY.audit.count(1)],
    ["audit.*", COPY.audit.end(false)],
    ["audit.*", COPY.audit.end(true)],
    ["audit.*", COPY.audit.cursorLost, " [Newest]"],
    ["audit.*", COPY.audit.error("{hh:mm:ss}"), " [Retry]"],
    ["audit.*", COPY.audit.limited("{hh:mm:ss}", 0).replace("0 s", "{s} s")],
    ["audit.*", COPY.audit.errRange],
    ["audit.*", COPY.audit.errIp],
    ["tamper.*", COPY.tamper.pagePassed],
    ["tamper.*", COPY.tamper.pagePartial],
    ["tamper.*", COPY.tamper.pagePartialOwn],
    ["tamper.*", COPY.tamper.newestPartial],
    ["tamper.*", COPY.tamper.incidentsUnavailable],
    ["tamper.*", COPY.tamper.checking],
    ["tamper.*", COPY.tamper.rangePassed("{from}–{to}", "{hh:mm}")],
    ["tamper.*", COPY.tamper.rangeEmpty],
    ["tamper.*", COPY.tamper.busy],
    ["tamper.*", COPY.tamper.limited("{hh:mm}")],
    ["tamper.*", COPY.tamper.stopped("{hh:mm:ss}")],
    ["tamper.*", COPY.tamper.stoppedEntry],
    ["tamper.*", COPY.tamper.failed.title("{n}")],
    ["tamper.*", COPY.tamper.failed.facts("{hh:mm:ss}", "{yyyy-mm-dd}", "{from}–{to}")],
    ["tamper.*", COPY.tamper.failed.meaning],
    ["tamper.*", COPY.tamper.failed.safe],
    ["tamper.*", COPY.tamper.failed.recheck],
    ["tamper.*", COPY.tamper.failed.steps],
    ["tamper.*", COPY.tamper.failed.copy],
    ["export.*", COPY.export.dlgTitle],
    ["export.*", COPY.export.dlgBody("{from}", "{to}")],
    ["export.*", COPY.export.dlgPii],
    ["export.*", COPY.export.dlgRange],
    ["export.*", COPY.export.dlgStarting],
    ["export.*", COPY.export.notBuilt],
    ["export.*", COPY.export.running(0, "{id8}").replace("0 %", "{n} %")],
    ["export.*", COPY.export.running(null, "{id8}")],
    ["export.*", COPY.export.pollFailed],
    ["export.*", COPY.export.trust],
    ["export.*", COPY.export.fail["export_too_large"] ?? ""],
    ["export.*", COPY.export.fail["signing_key_rotated"] ?? ""],
    ["export.*", COPY.export.fail["signing_unavailable"] ?? ""],
    ["export.*", COPY.export.fail["audit_unavailable"] ?? ""],
    ["export.*", COPY.export.fail["internal_error"] ?? ""],
    ["export.*", COPY.export.cancelled],
    ["export.*", COPY.export.lost],
    ["export.*", COPY.export.expired("{yyyy-mm-dd hh:mm}")],
    ["export.*", COPY.export.limited("{hh:mm}")],
    ["export.*", COPY.export.downloadFailed],
    ["export.*", COPY.export.unknown, " [Check again]"],
    ["export.*", COPY.export.refused.range("{days}")],
    ["export.*", COPY.export.refused.busy],
    ["export.*", COPY.export.refused.rate("{hh:mm}")],
    ["export.*", COPY.export.refused.signing],
    ["export.*", COPY.export.refused.store],
    ["export.*", COPY.export.notSent],
    ["rec.*", COPY.rec.immutable],
    ["rec.*", COPY.rec.role],
    ["rec.*", COPY.rec.agentNone],
    ["rec.*", COPY.rec.chain],
    ["rec.*", COPY.rec.verifiedTo("{from}–{to}", "{hh:mm}")],
    ["rec.*", COPY.rec.notChecked],
    ["rec.*", COPY.rec.afterBreak("{n}")],
    ["rec.*", COPY.rec.correlationNone],
    ["rec.*", COPY.rec.relatedActor],
    ["rec.*", COPY.rec.relatedSubject],
    ["rec.*", COPY.rec.relatedTime],
    ["rec.*", COPY.rec.rawFlagged],
    ["rec.*", COPY.rec.hidden],
    ["rec.*", COPY.rec.deletedUser("{12 hex}")],
    ["rec.*", COPY.rec.rawShow],
    ["admin.*", COPY.admin.rateLimited],
    ["admin.*", COPY.admin.newest],
    ["admin.*", COPY.admin.oldest(false)],
    ["admin.*", COPY.admin.oldest(true)],
    ["admin.*", COPY.admin.pageEdge],
    ["admin.*", COPY.admin.exportNotBuilt],
  ])("test_copy_%s_string_is_the_decks_whole: %s", (prefix: string, text: string, button = "") => {
    expect(row(prefix)).toContain(`"${text}${button}"`);
  });

  it("test_copy_ready_line_parts_are_the_decks_in_order", () => {
    const ready = [
      COPY.export.ready.lead("{rows}", "{from}", "{to}", "{size}"),
      COPY.export.ready.digest("{hex8}"),
      "[Copy]",
      COPY.export.ready.key("{key_id}"),
      COPY.export.ready.deleted("{yyyy-mm-dd hh:mm}"),
    ].join(" · ");
    expect(row("export.*")).toContain(`"${ready.replace("· [Copy] ·", "[Copy] ·")} [Download]"`);
  });

  it("test_copy_labels_are_the_decks_anatomy_strings", () => {
    const labels = row("labels.*");
    const words = [
      ...Object.values(COPY.labels.col),
      ...Object.values(COPY.labels.filter),
      ...Object.values(COPY.labels.page),
      ...Object.values(COPY.labels.field),
      ...Object.values(COPY.labels.word),
      COPY.labels.act.signedExport,
      COPY.labels.act.runTamperCheck,
      COPY.labels.act.download,
      COPY.labels.h.auditLog,
      COPY.labels.h.myActivity,
      COPY.labels.h.record("{id}"),
      COPY.labels.h.beforeAfter,
      COPY.labels.h.raw,
    ];
    for (const word of words) expect(labels).toContain(`"${word}"`);
  });

  it("test_copy_inherited_d09_strings_are_d09s", () => {
    expect(D09).toContain(`"${COPY.inflight.readOnly}"`);
    expect(D09).toContain(`"${COPY.inflight.notSent("{reason}")}"`);
    expect(COPY.inflight.notSent("")).toBe("Not sent — your access changed.");
  });
});

describe("PROPOSED strings stay marked (D04 owns them by A-row)", () => {
  it.each([
    ["tamper.failed.halted", COPY.tamper.failed.halted],
    ["tamper.failed.may_be_halted", COPY.tamper.failed.mayBeHalted],
    ["audit.limit_ended", COPY.audit.limitEnded],
    ["tamper.failed.title_unknown", COPY.tamper.failed.titleUnknown],
    ["tamper.failed.facts_incident", COPY.tamper.failed.factsIncident("{hh:mm:ss}", "{d}")],
    ["tamper.no_answer", COPY.tamper.noAnswer],
    ["tamper.not_run", COPY.tamper.notRun],
    ["audit.error without a time", COPY.audit.error(null)],
    ["audit.new_loaded singular", COPY.audit.newLoaded(1)],
  ])("test_copy_%s_is_not_the_decks", (_key, text) => {
    expect(DECK).not.toContain(text);
  });
});

describe("fills", () => {
  it("test_copy_fills_format_ids_times_and_sizes_as_section_1_does", () => {
    expect(num(1_204_118)).toBe("1,204,118");
    expect(num(41)).toBe("41");
    expect(range(204_119, 1_204_118)).toBe("204,119–1,204,118");
    const at = Date.UTC(2026, 9, 22, 14, 5, 7);
    expect(utc.hms(at)).toBe("14:05:07");
    expect(utc.hm(at)).toBe("14:05");
    expect(utc.date(at)).toBe("2026-10-22");
    expect(utc.dateHm(at)).toBe("2026-10-22 14:05");
    expect(size(512)).toBe("512 B");
    expect(size(44_120_000)).toBe("44.1 MB");
    expect(size(1_073_741_824)).toBe("1.1 GB");
    expect(COPY.audit.count(1_204)).toBe("1,204 entries on this page");
    expect(COPY.audit.newN(1, false)).toBe("1 new entry — show newest");
    expect(COPY.audit.envPage("live")).toBe("LIVE (this page only)");
    expect(COPY.export.running(42.7, "19000000")).toBe("Preparing the export… 42 % · job 19000000");
  });
});
