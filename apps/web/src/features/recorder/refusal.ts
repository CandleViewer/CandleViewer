/**
 * How the recorder screens word a refused call (E16-D06 §16.4): a deck sentence or the generic T4,
 * each with the code token after it in parentheses, or the app's words when nothing answered. A
 * deck route reads its row from the copy that holds it (`ROWS`: SCR-140's, SCR-141's or SCR-142's);
 * the T4's sentence and a row's `{verb}` follow SCR-140's actions (`RefusalAction`). The words come
 * from the route the client built (`recorderApi.ts`); a problem body's `message` and `detail` never
 * reach here (§20.3).
 */
import { DECK, fill } from "./copy";
import { formatClock, formatDate } from "./model";
import { PAGE_DECK, PAGE_TEXT } from "./pageCopy";
import type { RefusalDeckKey, RefusalRoute } from "./recorderApi";
import { RETENTION_DECK } from "./retention/retentionCopy";
import { STORAGE_DECK } from "./storage/storageCopy";

/**
 * Each refusal key's deck row, from the copy that holds it: this page's (`copy.ts`, `pageCopy.ts`,
 * listed last so its rows win), SCR-141's (`retentionCopy.ts`) or SCR-142's (`storageCopy.ts`). A
 * key the client adds without a row here fails to compile.
 */
const ROWS: Readonly<Record<RefusalDeckKey, readonly [string, ...string[]]>> = {
  ...RETENTION_DECK,
  ...STORAGE_DECK,
  ...DECK,
  ...PAGE_DECK,
};

/** The action a refusal answers: picks the T4's outcome word and the deck's `{verb}`. */
export type RefusalAction = "add" | "stop" | "compact";
const VERB: Readonly<Record<RefusalAction, string>> = {
  add: "start",
  stop: "stop",
  compact: "compaction",
};

/** "Sentence. (code)": the deck's form for a refusal at the point of action (E16-D04 `JOB/strip-refused-409`). */
const withCode = (sentence: string, code: string | null): string =>
  code === null ? sentence : `${sentence} (${code})`;

/** The words for `route`; `fills` names the row a deck sentence speaks of (`{symbol}`). */
export function refusalText(
  route: RefusalRoute,
  action: RefusalAction,
  fills: Readonly<Record<string, string>> = {},
): string {
  if (route.kind === "deck") {
    const [template] = ROWS[route.key];
    const at = route.serverTime === null ? Number.NaN : Date.parse(route.serverTime);
    const serverTime = Number.isNaN(at) ? "" : `${formatDate(at)} ${formatClock(at)} UTC`;
    const sentence = fill(template, {
      "{verb}": VERB[action],
      "{server_time}": serverTime,
      ...fills,
    });
    return withCode(sentence, route.code);
  }
  if (route.kind === "t4" && route.status === 0) return PAGE_TEXT.unreachable;
  const code = route.kind === "t4" ? route.code : "step_up_required";
  return withCode(PAGE_TEXT.refused[action], code);
}
