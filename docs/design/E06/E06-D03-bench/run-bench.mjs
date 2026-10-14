// Throwaway runner: drives headless Chromium over CDP. Usage: node run-bench.mjs <chrome> <html> <ms> <reps>
import {spawn} from 'node:child_process';
const [chrome,html,ms='20000',reps='3']=process.argv.slice(2);
const p=spawn(chrome,['--no-sandbox','--disable-gpu','--remote-debugging-port=9333','about:blank'],{stdio:'ignore'});
await new Promise(r=>setTimeout(r,2000));
const list=await (await fetch('http://127.0.0.1:9333/json')).json();
const ws=new WebSocket(list.find(t=>t.type==='page').webSocketDebuggerUrl);
await new Promise(r=>ws.onopen=r);let id=0;const pend=new Map();
ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id&&pend.has(m.id)){pend.get(m.id)(m);pend.delete(m.id);}};
const send=(method,params={})=>new Promise(r=>{const i=++id;pend.set(i,r);ws.send(JSON.stringify({id:i,method,params}));});
await send('Page.navigate',{url:`file://${html}?ms=${ms}&reps=${reps}&only=${process.env.ONLY||''}`});
for(;;){await new Promise(r=>setTimeout(r,2000));const r=await send('Runtime.evaluate',{expression:'document.getElementById("out").textContent'});const v=r.result.result.value;if(v&&v.startsWith('RESULT')){console.log(v.slice(6));break;}}
p.kill();process.exit(0);
