// utils/net.js

// ---------- Helpers ----------
function get(o, path) {
  return path.split('.').reduce((a, k) => (a && a[k] !== undefined ? a[k] : undefined), o);
}
function pickStr(...vals) {
  for (const v of vals) if (typeof v === 'string' && v.trim()) return v.trim();
  return '';
}

// Flacht mehrfach verschachtelte { result: {...} } Ebenen ab,
// bis echte Nutzdaten (answer/text/sources/artifacts) sichtbar sind.
function flattenToPayload(data) {
  let cur = data, hops = 0;
  while (
    cur &&
    typeof cur === 'object' &&
    !Array.isArray(cur) &&
    cur.result &&
    typeof cur.result === 'object' &&
    hops < 5
  ) {
    // Break, sobald die "innenliegende" Ebene Nutzdaten enthält
    if (
      typeof cur.result.answer === 'string' ||
      typeof cur.result.text === 'string' ||
      Array.isArray(cur.result.sources) ||
      cur.result.artifacts
    ) break;
    cur = cur.result;
    hops++;
  }
  return cur?.result && typeof cur.result === 'object' ? cur.result : cur;
}

// Extrahiert final die Felder (answer, sources, artifacts) tolerant.
function extractResultFields(raw) {
  const flat = flattenToPayload(raw);
  const answer = pickStr(
    flat?.answer,
    flat?.text,
    get(raw, 'result.answer'),
    get(raw, 'result.result.answer'), // Doppelnesting (dein Fall vorher)
    get(raw, 'result.text'),
    get(raw, 'choices.0.message.content'),
    get(raw, 'choices.0.text'),
    get(raw, 'data.choices.0.message.content')
  );
  const sources =
    flat?.sources ??
    flat?.documents ??
    raw?.sources ??
    raw?.documents ?? [];
  const artifacts =
    flat?.artifacts ??
    raw?.artifacts ?? {};
  return { answer: answer || '', sources, artifacts, raw };
}

// ---------- Exporte ----------

// Prüft, ob URL brauchbar (gleiches Origin, /rag/*).
export function looksOk(url) {
  if (typeof url !== 'string' || !url) return false;
  if (url.includes('{{') || url.includes('$json')) return false;
  try {
    const u = new URL(url, location.href);
    return u.origin === location.origin && u.pathname.startsWith('/rag/');
  } catch {
    return false;
  }
}

// Pollt, bis /result ein verwertbares Ergebnis liefert.
export async function waitForResult(url, { maxWaitMs = 300000, pollMs = 1200 } = {}) {
  const t0 = Date.now();
  for (;;) {
    const r = await fetch(url, {
      method: 'GET',
      headers: { 'Accept': 'application/json' },
      cache: 'no-store',
    });
    if (r.ok) {
      let j = null;
      try { j = await r.json(); } catch {}
      if (j) {
        const parsed = extractResultFields(j);
        const doneLike = j?.status === 'done' || !!j?.result; // tolerant
        
        console.debug('[result-poll][about-to-return]', {
          rawStatus: j?.status,
          typeofResult: typeof j?.result,
          hasAnswerInRaw: !!(j?.result && (j.result.answer || j.result.text)),
          parsedPreview: String(parsed?.answer || parsed?.text || '').slice(0,120)
        });

        if (parsed.answer || doneLike) return parsed;
      }
    }
    if (Date.now() - t0 > maxWaitMs) {
      throw new Error('Timeout – kein Ergebnis verfügbar.');
    }
    await new Promise(res => setTimeout(res, pollMs));
  }
}

// Dünner Wrapper um EventSource.
export function startEventSource(eventsUrl, { onOpen, onError, onEvent }) {
  try { window.__es?.close?.(); } catch {}
  const src = new EventSource(eventsUrl, { withCredentials: true });
  window.__es = src;
  if (onOpen)  src.onopen = onOpen;
  if (onError) src.onerror = onError;
  if (onEvent) src.onmessage = onEvent;
  return src;
}
