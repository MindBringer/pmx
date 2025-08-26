// features/syncChat.js
import { setFinalAnswer, setError } from "../ui/renderers.js";
import { getConversationId, isValidConversationId } from "../state/conversation.js";

// --- kleine lokale Parser-Helfer (ähnlich utils/net.js), bewusst lokal gehalten ---
function get(o, path) {
  return path.split('.').reduce((a, k) => (a && a[k] !== undefined ? a[k] : undefined), o);
}
function pickStr(...vals) {
  for (const v of vals) if (typeof v === 'string' && v.trim()) return v.trim();
  return '';
}
function flattenToPayload(data) {
  let cur = data, hops = 0;
  while (
    cur && typeof cur === 'object' && !Array.isArray(cur) &&
    cur.result && typeof cur.result === 'object' && hops < 5
  ) {
    // Break, sobald innen Nutzdaten liegen
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
function extractResultFields(raw) {
  const flat = flattenToPayload(raw || {});
  const answer = pickStr(
    flat?.answer,
    flat?.text,
    get(raw, 'result.result.answer'),
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

// --- Hauptroutine: synchroner Run über n8n ---
export async function startSyncRun(title, payload) {
  try {
    const headers = { "Content-Type": "application/json" };
    const convId = getConversationId();
    if (isValidConversationId(convId)) {
      headers["x-conversation-id"] = convId;
      payload.conversation_id = convId;
    }

    // Optional: UI-API-Key ins Payload, n8n reicht ihn an RAG weiter
    const apiKey = (localStorage.getItem('ragApiKey') || '').trim();
    if (apiKey) payload.rag_api_key = apiKey;

    // Wichtig: NICHT /query, sondern der n8n-Webhook
    const res = await fetch("/webhook/llm", {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });

    const text = await res.text(); // n8n kann ein '=' Prefix senden
    let json = null;
    try { json = JSON.parse(text.trim().replace(/^=\s*/, "")); } catch {}

    if (!res.ok) {
      setError(json?.message || json?.error || `HTTP ${res.status}: ${text.slice(0, 256)}`);
      return;
    }

    const { answer, sources, artifacts } = extractResultFields(json || {});
    try {
      // renderers.setFinalAnswer akzeptiert die Objekt-Signatur
      setFinalAnswer({ answer: (answer || "[leer]"), sources, artifacts });
    } catch (e) {
      setError(`Antwort-Rendering fehlgeschlagen: ${e?.message || e}`);
    }
  } catch (e) {
    setError(`Sync-Run Fehler: ${e?.message || e}`);
  }
}
