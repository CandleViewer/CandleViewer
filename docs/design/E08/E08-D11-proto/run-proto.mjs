// E08-D11 prototype runner: drives headless Chromium over the DevTools protocol and prints the page's result JSON.
// Usage: node --experimental-websocket run-proto.mjs <chrome> <html> [<ms> <reps>]   (Node 20; Node 22+ needs no flag)
// <chrome> is a headless Chromium (the Playwright chrome-headless-shell works); <html> is the absolute path of
// motion-proto.html; <ms> is the per-rep frame window (default 400) and <reps> the repetitions (default 5).
// No network: the browser's DevTools endpoint is read from Chrome's own stderr ("DevTools listening on …") and
// the page is a local file. Redirect stdout to proto-results.json to commit a run.
/* global process, WebSocket, setTimeout, console */
import { spawn } from "node:child_process";
const [chrome, html, ms = "400", reps = "5"] = process.argv.slice(2);
if (!chrome || !html) {
  console.error("usage: node --experimental-websocket run-proto.mjs <chrome> <html> [<ms> <reps>]");
  process.exit(2);
}
const p = spawn(
  chrome,
  ["--no-sandbox", "--disable-gpu", "--remote-debugging-port=0", "about:blank"],
  {
    stdio: ["ignore", "ignore", "pipe"],
  },
);
const endpoint = await new Promise((resolve, reject) => {
  let err = "";
  p.stderr.on("data", (d) => {
    err += d;
    const m = err.match(/DevTools listening on (\S+)/);
    if (m) resolve(m[1]);
  });
  p.on("exit", (code) => reject(new Error(`chrome exited (${code})`)));
});
const ws = new WebSocket(endpoint);
await new Promise((r) => (ws.onopen = r));
let id = 0;
const pend = new Map();
ws.onmessage = (e) => {
  const m = JSON.parse(e.data);
  if (m.id && pend.has(m.id)) {
    pend.get(m.id)(m);
    pend.delete(m.id);
  }
};
const send = (method, params = {}, sessionId) =>
  new Promise((r) => {
    const i = ++id;
    pend.set(i, r);
    ws.send(JSON.stringify({ id: i, method, params, ...(sessionId ? { sessionId } : {}) }));
  });
const { targetInfos } = (await send("Target.getTargets")).result;
const target = targetInfos.find((t) => t.type === "page");
const { sessionId } = (
  await send("Target.attachToTarget", { targetId: target.targetId, flatten: true })
).result;
await send("Page.navigate", { url: `file://${html}?ms=${ms}&reps=${reps}` }, sessionId);
for (;;) {
  await new Promise((r) => setTimeout(r, 1000));
  const r = await send(
    "Runtime.evaluate",
    { expression: 'document.getElementById("out").textContent' },
    sessionId,
  );
  const v = r.result.result.value;
  if (v && v.startsWith("RESULT")) {
    console.log(v.slice(6));
    break;
  }
}
p.kill();
process.exit(0);
