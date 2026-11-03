/**
 * E42-S04 (#1135): the audit pages' polite lines (E42-D04 §12; the build plan's §5) go through the
 * shell's one announcer, each once, at most one per `REGION_BUDGET_MS` behind any writer's last
 * line; leaving the page drops what waits and forgets what was said.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  REGION_BUDGET_MS,
  announce,
  clearAnnouncements,
  lastWrittenAt,
} from "../../../../src/features/app-shell/announcer";
import { createPageVoice } from "../../../../src/features/admin/audit/pageVoice";

const T0 = Date.UTC(2026, 9, 22, 14, 2, 11);

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(T0);
  clearAnnouncements();
});

afterEach(() => {
  clearAnnouncements();
  vi.useRealTimers();
});

describe("the page's voice", () => {
  it("test_voice_says_a_line_at_once_and_the_next_one_a_budget_later", async () => {
    const voice = createPageVoice();
    voice.say("2 entries on this page", "a");
    expect(lastWrittenAt("polite")).toBe(T0);
    voice.say("No older entries.", "b");
    await vi.advanceTimersByTimeAsync(REGION_BUDGET_MS - 1);
    expect(lastWrittenAt("polite")).toBe(T0);
    await vi.advanceTimersByTimeAsync(1);
    expect(lastWrittenAt("polite")).toBe(T0 + REGION_BUDGET_MS);
    voice.end();
  });

  it("test_voice_says_a_line_once_until_the_page_ends", () => {
    const voice = createPageVoice();
    voice.say("2 entries on this page", "a");
    voice.say("2 entries on this page", "a");
    expect(announce("polite", "2 entries on this page", "a")).toBe(false); // said already
    voice.end();
    expect(announce("polite", "2 entries on this page", "a")).toBe(true); // forgotten
  });

  it("test_voice_waits_behind_another_writers_line_and_drops_what_waits_when_it_ends", async () => {
    announce("polite", "another writer", "other");
    const voice = createPageVoice();
    voice.say("2 entries on this page", "a");
    expect(lastWrittenAt("polite")).toBe(T0); // the other writer's line
    voice.end();
    await vi.advanceTimersByTimeAsync(REGION_BUDGET_MS * 2);
    expect(lastWrittenAt("polite")).toBe(T0);
    expect(vi.getTimerCount()).toBe(0);
  });
});
