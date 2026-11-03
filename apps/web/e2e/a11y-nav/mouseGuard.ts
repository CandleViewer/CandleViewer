import type { Page } from "@playwright/test";

/**
 * The keyboard-only suite's structural mouse ban (E47-Q03 BQ-04 (a), 05-accessibility-standard.md s9.4).
 * `guardPage` wraps a Playwright Page (and every Locator / Frame it hands out) in a Proxy that throws on
 * any pointer-driven API, naming it. The in-page event counter in fixtures.ts stays as the second line: it
 * catches pointer events a script produces from inside the page (e.g. an `evaluate` calling `.click()`).
 */
export const FORBIDDEN_POINTER_APIS: ReadonlySet<string> = new Set([
  "click",
  "dblclick",
  "tap",
  "hover",
  "dragTo",
  "dragAndDrop",
  "check",
  "uncheck",
  "setChecked",
  "mouse",
  "touchscreen",
]);

const POINTER_EVENT = /^(click|dblclick|auxclick|contextmenu|mouse|pointer|touch|drag|drop)/i;

export class ForbiddenPointerApiError extends Error {
  constructor(api: string) {
    super(
      `A11Y-K001 forbidden pointer API "${api}": the keyboard-only suite never issues a mouse event`,
    );
    this.name = "ForbiddenPointerApiError";
  }
}

const isObject = (v: unknown): v is object =>
  (typeof v === "object" || typeof v === "function") && v !== null;
const isThenable = (v: object): boolean => typeof (v as { then?: unknown }).then === "function";

function wrap<T extends object>(target: T, path: string): T {
  return new Proxy(target, {
    get(obj, prop) {
      const name = typeof prop === "string" ? prop : "";
      const here = `${path}.${name}`;
      if (FORBIDDEN_POINTER_APIS.has(name)) {
        // Throws at the call (page.click(...)); page.mouse / page.touchscreen throw on any member.
        const refuse = (): never => {
          throw new ForbiddenPointerApiError(here);
        };
        if (name !== "mouse" && name !== "touchscreen") return refuse;
        return new Proxy(refuse, {
          get: (_t, member) => (): never => {
            throw new ForbiddenPointerApiError(`${here}.${String(member)}`);
          },
        });
      }
      const value: unknown = Reflect.get(obj, prop, obj);
      if (typeof value !== "function") return value;
      return (...args: unknown[]): unknown => {
        if (
          name === "dispatchEvent" &&
          typeof args[0] === "string" &&
          POINTER_EVENT.test(args[0])
        ) {
          throw new ForbiddenPointerApiError(`${here}("${args[0]}")`);
        }
        const out: unknown = (value as (...a: unknown[]) => unknown).apply(obj, args);
        return isObject(out) && !isThenable(out) ? wrap(out, `${here}()`) : out;
      };
    },
  });
}

/** Wrap `page` so any pointer API throws {@link ForbiddenPointerApiError}. */
export function guardPage(page: Page): Page {
  return wrap(page, "page");
}
