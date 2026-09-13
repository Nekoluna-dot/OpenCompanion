import { app } from "./state.js";

let es = null;
const subs = new Set();

export function subscribeLogs(cb) {
  subs.add(cb);
  return () => subs.delete(cb);
}

export function pushLog(line) {
  app.logs.push(line);
  if (app.logs.length > 2000) app.logs.splice(0, app.logs.length - 2000);
  app.logSeq++;
  subs.forEach(cb => { try { cb(line); } catch (e) {} });
}

export function startSse() {
  if (es) return;
  const q = app.token ? "?token=" + encodeURIComponent(app.token) : "";
  es = new EventSource("/api/logs/stream" + q);
  es.onmessage = ev => {
    app.sseOk = true;
    try { pushLog(JSON.parse(ev.data)); } catch (e) { pushLog(ev.data); }
  };
  es.onerror = () => {
    app.sseOk = false;
    if (es) { es.close(); es = null; }
    setTimeout(() => { if (es === null) startSse(); }, 2000);
  };
}

export function stopSse() {
  if (es) { es.close(); es = null; }
}
