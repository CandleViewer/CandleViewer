import type { Page } from "@playwright/test";

/**
 * The structural mouse ban (E47-Q03 BQ-04 (a), s9.4): `guardPage` Proxies a Page and everything it hands out,
 * throwing on any pointer API and naming it. fixtures.ts adds an in-page event counter as the second line.
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

/** A page, frame, locator, element handle or browser context: anything that can reach a pointer API. */
const isGuardable = (v: object): boolean =>
  typeof (v as { click?: unknown }).click === "function" ||
  typeof (v as { dispatchEvent?: unknown }).dispatchEvent === "function" ||
  typeof (v as { pages?: unknown }).pages === "function";

/**
 * Guard what a call hands back: the awaited value of a promise, each element of an array (`locator.all()`,
 * `frames()`, `context().pages()`), and any guardable object (locators, frames, ElementHandles from
 * `$`, `$$`, `elementHandle()` and `waitForSelector`, the page's context).
 */
function wrapResult(value: unknown, path: string): unknown {
  if (!isObject(value)) return value;
  if (isThenable(value)) {
    return (value as Promise<unknown>).then((v) => wrapResult(v, path));
  }
  if (Array.isArray(value)) return value.map((v, i) => wrapResult(v, `${path}[${i}]`));
  return isGuardable(value) ? wrap(value, path) : value;
}

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
        return wrapResult((value as (...a: unknown[]) => unknown).apply(obj, args), `${here}()`);
      };
    },
  });
}

/** Wrap `page` so any pointer API throws {@link ForbiddenPointerApiError}. */
export function guardPage(page: Page): Page {
  return wrap(page, "page");
}
