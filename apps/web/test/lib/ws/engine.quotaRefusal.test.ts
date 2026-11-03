// E21-X02 (#652; 23 §5.2, §5.4, §10.3, Gherkin "Quota enforced and explained"): a topic the gateway
// refuses for a subscription quota (`subscription_limit`) is ended and never asked for again, not
// on the next reconciliation pass and not after a reconnect, so the client never retries in a
// loop; and a quota refusal that reaches the error handler (a `ctl`'s `err`) is shown as the
// polite capacity notice, the explanation 10.3 gives the code. No new UI text: the notice is
// WsErrorHost's own.
import { act, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CTL_DEBOUNCE_MS } from "../../../src/lib/ws/policy/ctlDebouncer";
import { WsErrorHost } from "../../../src/lib/ws/WsErrorHost";
import { handleWsError } from "../../../src/lib/ws/errorHandler";
import { BOOK, engineHarness, spec } from "./support/engineHarness";
import type { Json } from "./support/fakeGateway";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

const DEEP = "book.BTCUSDT.500";
const LIMIT = "subscription_limit";

/** Every topic every connection of the gateway was asked for, in order. */
function everySub(t: ReturnType<typeof engineHarness>): string[] {
  return t.gateway.conns.flatMap((conn) =>
    conn
      .of("sub")
      .flatMap((frame) => ((frame["p"] as Json)["topics"] as { ch: string }[]).map((x) => x.ch)),
  );
}

describe("Quota enforced and explained", () => {
  it("Quota enforced and explained: a refused deep topic is never sent again", async () => {
    const t = engineHarness();
    t.gateway.refuseTopic(DEEP, LIMIT);
    const deep = t.engine.consume(spec(DEEP));
    const book = t.engine.consume(spec(BOOK));
    await t.start();
    expect([deep.status, t.got(DEEP)]).toEqual(["revoked", ["reset:revoked"]]);
    expect(book.status).not.toBe("revoked");
    t.engine.consume(spec("trades.BTCUSDT")); // another pass of the reconciliation
    await t.advance(60_000);
    t.gateway.latest.close(1011); // the connection drops: the engine reconnects and subscribes afresh
    await t.advance(60_000);
    expect(t.gateway.conns.length).toBeGreaterThan(1);
    expect(everySub(t).filter((ch) => ch === DEEP)).toEqual([DEEP]); // asked once, ever
    expect(everySub(t).filter((ch) => ch === BOOK)).toEqual([BOOK, BOOK]); // the held one is asked again
    expect(t.gateway.conns.flatMap((conn) => conn.of("unsub"))).toEqual([]);
  });

  it("Quota enforced and explained: a refused ctl reaches the polite capacity notice", async () => {
    const errors: [string, string | undefined][] = [];
    const t = engineHarness(undefined, {
      sink: {
        event: () => undefined,
        deliver: () => undefined,
        error: (code, message) => void errors.push([code, message]),
      },
    });
    t.engine.consume(spec(BOOK));
    await t.start();
    t.engine.setPane("p1", { visibility: "offscreen", tabHidden: false }); // a slower throttle
    await t.advance(CTL_DEBOUNCE_MS + 100);
    expect(errors).toEqual([]);
    t.gateway.refuseCtls(1, LIMIT); // the quota refuses the faster throttle of a pane back in view
    t.engine.setPane("p1", { visibility: "visible", tabHidden: false });
    await t.advance(CTL_DEBOUNCE_MS + 100);
    expect(errors).toEqual([[LIMIT, "budget"]]);
    await t.advance(120_000);
    expect(t.gateway.latest.of("ctl")).toHaveLength(2); // the refused one is never re-sent in a loop

    vi.useRealTimers();
    render(createElement(WsErrorHost));
    const [code, message] = errors[0] ?? [LIMIT, undefined];
    act(
      () =>
        void handleWsError({ t: "err", p: { code, ...(message !== undefined && { message }) } }),
    );
    const notice = screen.getByRole("status");
    expect(notice.getAttribute("aria-live")).toBe("polite");
    expect(notice.textContent).toBe(
      "Server capacity reached (subscription_limit). Try fewer panes.",
    );
    expect(screen.queryByRole("alertdialog")).toBeNull(); // capacity is never a modal (10.3)
  });
});
