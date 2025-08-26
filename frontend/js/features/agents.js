// agents.js
import { looksOk, waitForResult, startEventSource } from "../utils/net.js";
import { setFinalAnswer, setError, showJob, logJob, sseLabel } from "../ui/renderers.js";
import { getConversationId, isValidConversationId } from "../state/conversation.js";

export function collectPersonas(){
  const rows = [1,2,3,4,5];
  const list = [];
  for (const i of rows){
    const en = document.getElementById(`p${i}_enabled`);
    const labEl = document.getElementById(`p${i}_label`);
    const modEl = document.getElementById(`p${i}_model`);
    if (!en || !labEl || !modEl) continue;
    const checked = !!en.checked;
    const label = (labEl.value||'').trim();
    const provider = modEl.value;
    if (checked){
      if (!label){
        throw new Error(`Bitte Jobtitel/Beschreibung für Persona ${i} eingeben.`);
      }
      list.push({ label, provider });
    }
  }
  return list;
}

export async function startAsyncRun(job_title, payload){
  const headers = { "Content-Type": "application/json" };
  const convId = getConversationId();
  if (isValidConversationId(convId)) {
    payload.conversation_id = convId;
    headers["x-conversation-id"] = convId;
  }
  payload.async = true;
  payload.title = job_title;

  // Start via n8n Webhook
  const res = await fetch("/webhook/llm", { method: "POST", headers, body: JSON.stringify(payload) });
  const ackText = await res.text();
  let ack = {};
  try { ack = JSON.parse(ackText.trim().replace(/^=\s*/, "")); } catch {}

  // jobId extrahieren
  const jobId =
    ack.job_id ||
    (typeof ack.events === "string" && ack.events.match(/\/rag\/jobs\/([^/]+)/)?.[1]) ||
    (typeof ack.result === "string" && ack.result.match(/\/rag\/jobs\/([^/]+)/)?.[1]) ||
    "";

  if (!res.ok || !jobId) {
    setError(ack?.message || ack?.error || `Start fehlgeschlagen (${res.status})`);
    throw new Error("start failed");
  }
  ack.job_id = jobId;

  showJob(job_title || payload?.prompt || "Agentenlauf");

  // Events-/Result-URL stabilisieren
  const eventsUrl = looksOk(ack.events) ? ack.events : `/rag/jobs/${encodeURIComponent(jobId)}/events`;
  const resultUrl = looksOk(ack.result) ? ack.result : `/rag/jobs/${encodeURIComponent(jobId)}/result`;

  // SSE verbinden
    const src = startEventSource(eventsUrl, {
    onOpen:  () => logJob("SSE verbunden."),
    onError: () => logJob("Stream-Fehler (SSE) – versuche verbunden zu bleiben …"),
    onEvent: (e) => {
      try {
        const evt = JSON.parse(e.data);
        const line = document.getElementById('job-statusline');
        if (line) line.textContent = sseLabel(job_title, evt);
        if (evt.message) logJob(evt.message);

        if (evt.status === 'done' || evt.stage === 'done' || evt.done === true) {
          completeNow();
        }
      } catch {
        logJob(String(e.data || 'Event ohne JSON'));
      }
    }
  });

  // ---------- robuste Extraktion ----------
  function get(o, path) {
    return path.split('.').reduce((a,k)=> (a && a[k]!==undefined ? a[k] : undefined), o);
  }
  function pickStr(...vals){
    for (const v of vals) if (typeof v === 'string' && v.trim()) return v.trim();
    return '';
  }
  function extractAnyResult(raw){
    const answer = pickStr(
      get(raw,'result.result.answer'),
      get(raw,'result.answer'),
      raw?.answer,
      get(raw,'result.text'),
      raw?.text,
      get(raw,'choices.0.message.content'),
      get(raw,'choices.0.text'),
      get(raw,'data.choices.0.message.content')
    );
    const sources =
      get(raw,'result.result.sources') ??
      get(raw,'result.sources') ??
      raw?.sources ??
      get(raw,'result.documents') ??
      raw?.documents ?? [];
    const artifacts =
      get(raw,'result.result.artifacts') ??
      get(raw,'result.artifacts') ??
      raw?.artifacts ?? {};
    return { answer: answer || '', sources, artifacts };
  }
  async function fetchResultOnce(url){
    const r = await fetch(url, { headers: { 'Accept': 'application/json' }, cache: 'no-store' });
    if (!r.ok) throw new Error(`GET ${url} -> ${r.status}`);
    const raw = await r.json();
    return { raw, ...extractAnyResult(raw) };
  }
  async function pollResult(url, maxMs=300000, stepMs=1200){
    const t0 = Date.now();
    for(;;){
      try {
        const got = await fetchResultOnce(url);
        const doneLike = got.raw?.status === 'done' || !!got.raw?.result;
        if (got.answer || doneLike) return got;
      } catch {}
      if (Date.now()-t0 > maxMs) throw new Error('Timeout – kein Ergebnis verfügbar.');
      await new Promise(r=>setTimeout(r, stepMs));
    }
  }
  // ---------------------------------------

  let finished = false;
  async function renderFinal(got){
    if (finished) return;
    finished = true;
    try { src.close(); } catch {}

    try {
      if (!got) got = await fetchResultOnce(resultUrl); // einmalig holen (Result existiert bei dir ja schon)
      const answer = (got.answer || '').trim();
      const sources = got.sources || [];
      const artifacts = got.artifacts || {};

      // Kompatibel beide Signaturen bedienen
      // setFinalAnswer kann zwei Signaturen haben – probier beide:
      let ok = false;
      try { setFinalAnswer(answer || '[leer1]', { sources, artifacts }); ok = true; } catch {}
      if (!ok) { try { setFinalAnswer({ answer: (answer || '[leer2]'), sources, artifacts }); ok = true; } catch {} }
      if (!ok)  { const el = document.querySelector('#final-answer'); if (el) el.textContent = (answer || '[leer3]'); }
    } catch (e) {
      console.error("Final rendering failed", e);
      try { setFinalAnswer("[leer]"); } catch {}
    }
  }

  // Poller: IMMER starten; sobald /result etwas hat, rendern
  (async () => {
    try {
      const got = await pollResult(resultUrl);
      await renderFinal(got);
    } catch (e) {
      console.error("waitForResult failed", e);
    }
  })();

  async function completeNow(){
    try { await renderFinal(); } catch (e) { console.error("completeNow()", e); }
  }

}
