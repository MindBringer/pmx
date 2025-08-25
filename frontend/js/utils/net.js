
export function looksOk(url){
  if (typeof url !== 'string' || !url) return false;
  if (url.includes('{{') || url.includes('$json')) return false;
  try {
    const u = new URL(url, location.href);
    return u.origin === location.origin && (u.pathname.startsWith('/rag/jobs/') || u.pathname.startsWith('/rag/'));
  } catch { return false; }
}
export async function waitForResult(url, { maxWaitMs = 300000, pollMs = 1200 } = {}) {
  const t0 = Date.now();
  for (;;) {
    try {
      const r = await fetch(url, { headers: { 'Accept': 'application/json' } });
      if (r.ok) {
        const j = await r.json();
        if (j?.status === 'done' || j?.result) return j;
      }
    } catch {}
    if (Date.now() - t0 > maxWaitMs) throw new Error('Timeout – kein Ergebnis verfügbar.');
    await new Promise(r => setTimeout(r, pollMs));
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
