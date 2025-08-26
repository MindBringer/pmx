// net.js
export function looksOk(url){
  if (typeof url !== 'string' || !url) return false;
  if (url.includes('{{') || url.includes('$json')) return false;
  try {
    const u = new URL(url, location.href);
    // gleiches Origin + /rag/* reicht uns
    return u.origin === location.origin && (u.pathname.startsWith('/rag/'));
  } catch { return false; }
}

export async function waitForResult(url, { maxWaitMs = 300000, pollMs = 1200 } = {}) {
  const t0 = Date.now();
  /* Wir warten, bis entweder:
     - status === "done" ODER
     - ein answer-Text vorhanden ist ODER
     - ein result-Objekt existiert (Backend-spezifisch)
  */
  for (;;) {
    const r = await fetch(url, { method: 'GET', headers: { 'Accept': 'application/json' }, cache: 'no-store' });
    if (r.ok) {
      let j;
      try { j = await r.json(); } catch { j = null; }
      if (j) {
        const ans = (j?.result?.answer ?? j?.answer ?? '').trim();
        const done = j?.status === 'done' || !!j?.result;
        if (ans || done) return j;
      }
    }
    if (Date.now() - t0 > maxWaitMs) throw new Error('Timeout – kein Ergebnis verfügbar.');
    await new Promise(res => setTimeout(res, pollMs));
  }
}

export function startEventSource(eventsUrl, { onOpen, onError, onEvent }){
  try { window.__es?.close?.(); } catch {}
  const src = new EventSource(eventsUrl, { withCredentials: true });
  window.__es = src;
  if (onOpen)  src.onopen = onOpen;
  if (onError) src.onerror = onError;
  if (onEvent) src.onmessage = onEvent;
  return src;
}
