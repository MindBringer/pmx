// net.js
function get(obj, path) {
  return path.split('.').reduce((a, k) => (a && a[k] !== undefined ? a[k] : undefined), obj);
}
function pickStr(...cands) {
  for (const v of cands) if (typeof v === 'string' && v.trim()) return v.trim();
  return '';
}
function extractResultFields(data) {
  // deckt {result:{answer}}, {answer}, {result:{result:{answer}}}, {text}, OpenAI/Claude-Formen ab
  const answer = pickStr(
    get(data, 'result.answer'),
    data && data.answer,
    get(data, 'result.result.answer'),
    get(data, 'result.text'),
    data && data.text,
    get(data, 'choices.0.message.content'),
    get(data, 'choices.0.text'),
    get(data, 'data.choices.0.message.content')
  );

  const sources =
    get(data, 'result.sources') ??
    data?.sources ??
    get(data, 'result.result.sources') ??
    get(data, 'result.documents') ??
    data?.documents ??
    [];

  const artifacts =
    get(data, 'result.artifacts') ??
    data?.artifacts ??
    get(data, 'result.result.artifacts') ??
    {};

  return { answer: answer || '', sources, artifacts, raw: data };
}

export function looksOk(url){
  if (typeof url !== 'string' || !url) return false;
  if (url.includes('{{') || url.includes('$json')) return false;
  try {
    const u = new URL(url, location.href);
    return u.origin === location.origin && u.pathname.startsWith('/rag/');
  } catch { return false; }
}

// Pollt, bis ein Ergebnis da ist. Liefert bereits extrahierte Felder zurück.
export async function waitForResult(url, { maxWaitMs = 300000, pollMs = 1200 } = {}) {
  const t0 = Date.now();
  for (;;) {
    const r = await fetch(url, { method: 'GET', headers: { 'Accept': 'application/json' }, cache: 'no-store' });
    if (r.ok) {
      let j = null;
      try { j = await r.json(); } catch {}
      if (j) {
        const parsed = extractResultFields(j);
        const doneLike = j?.status === 'done' || !!j?.result;
        if (parsed.answer || doneLike) return parsed;
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
