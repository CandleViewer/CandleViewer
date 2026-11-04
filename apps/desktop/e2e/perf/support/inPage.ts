// E10-Q04 PR-3: the page side of the route, rail and chip benches, installed with `addInitScript`
// as `window.cvBench`. Plain JavaScript in a string because this app's TypeScript has no DOM lib;
// every timing is taken in the page (performance.now, rAF), never across the Playwright channel.
export const IN_PAGE = String.raw`
window.cvBench = (() => {
  const raf = () => new Promise((r) => requestAnimationFrame(() => r(performance.now())));
  const main = () => document.getElementById("cv-main");
  const rail = () => document.querySelector('nav[aria-label="Primary"]');
  const clock = () => /\d\d:\d\d:\d\d UTC/.exec(document.querySelector("footer")?.textContent ?? "")?.[0];
  return {
    /** Clicks the rail link to path; resolves at the frame after focus lands in main (BQ-05). */
    navigate(path) {
      return new Promise((resolve, reject) => {
        const link = rail()?.querySelector('a[href="' + path + '"]');
        if (!link) return reject(new Error("no rail link " + path));
        const seen = performance.getEntriesByType("resource").length;
        // Focus leaves main first, so the route's focus always fires a focusin, even when it lands
        // on main again (a route with no h1 after another).
        if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
        const timer = setTimeout(() => reject(new Error("focus never reached " + path)), 10000);
        const t0 = performance.now();
        const onFocus = (e) => {
          if (!location.pathname.startsWith(path) || !main()?.contains(e.target)) return;
          document.removeEventListener("focusin", onFocus, true);
          clearTimeout(timer);
          requestAnimationFrame(() => {
            const ms = performance.now() - t0;
            const jsBytes = performance.getEntriesByType("resource").slice(seen)
              .filter((r) => r.initiatorType === "script" || /\.m?js(\?|$)/.test(r.name))
              .reduce((n, r) => n + r.transferSize, 0);
            resolve({ ms, jsBytes });
          });
        };
        document.addEventListener("focusin", onFocus, true);
        link.click();
      });
    },
    /** A WebGL2 canvas in main, standing in for the chart (BQ-06: no engine in R0). */
    glProbe() {
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = 64;
      const gl = canvas.getContext("webgl2");
      window.cvGl = { canvas, gl, lost: 0 };
      canvas.addEventListener("webglcontextlost", () => { window.cvGl.lost += 1; });
      main().append(canvas);
      return gl !== null;
    },
    glState() {
      const p = window.cvGl;
      return { attached: main().contains(p.canvas), lost: p.lost, contextLost: p.gl.isContextLost() };
    },
    /** One rail toggle just after the 1 Hz clock ticks, every frame marked for the trace. */
    async toggleRail() {
      const at = clock();
      while (clock() === at) await raf();
      await raf();
      performance.mark("cv-rail-start");
      const t0 = performance.now();
      rail().querySelector("button[aria-expanded]").click();
      let done = false;
      let frames = 0;
      const looping = (async () => {
        while (!done) { await raf(); performance.mark("cv-rail-frame"); frames += 1; }
      })();
      await raf();
      const anims = document.getAnimations().filter((a) => rail().contains(a.effect?.target));
      const declaredMs = Math.max(0, ...anims.map((a) => a.effect.getComputedTiming().endTime));
      await Promise.all(anims.map((a) => a.finished.catch(() => undefined)));
      const measuredMs = performance.now() - t0;
      // The first frame mark at or after this one is the end boundary frame (R-2).
      performance.mark("cv-rail-finished");
      done = true;
      await looping;
      performance.mark("cv-rail-end");
      const durationsMs = [...rail().querySelectorAll("a span")]
        .flatMap((s) => getComputedStyle(s).transitionDuration.split(","))
        .map((t) => (t.trim().endsWith("ms") ? parseFloat(t) : parseFloat(t) * 1000));
      return { measuredMs, declaredMs, animations: anims.length, frames, durationsMs };
    },
    /** Counts 1 Hz clock ticks and live-region text changes from now on (AC3 a11y line). */
    watchChrome() {
      const state = { ticks: 0, said: 0, last: clock() };
      new MutationObserver(() => {
        const now = clock();
        if (now !== state.last) { state.ticks += 1; state.last = now; }
      }).observe(document.querySelector("footer"), { subtree: true, childList: true, characterData: true });
      const said = new MutationObserver(() => { state.said += 1; });
      for (const region of document.querySelectorAll("[aria-live]"))
        said.observe(region, { subtree: true, childList: true, characterData: true });
      window.cvChrome = state;
    },
  };
})();
`;
