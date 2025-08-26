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

  let finished = false;

  async function renderFinal(parsed){ // parsed kommt jetzt schon aus waitForResult extrahiert
    if (finished) return;
    finished = true;
    try { src.close(); } catch {}

    try {
      if (!parsed) parsed = await waitForResult(resultUrl); // -> {answer, sources, artifacts, raw}
      const answer = (parsed?.answer || '').trim();
      const sources = parsed?.sources || [];
      const artifacts = parsed?.artifacts || {};

      // setFinalAnswer kann (string, opts) oder ({answer,...}) sein: beide Varianten probieren
      let ok = false;
      try { setFinalAnswer(answer || "[leer]", { sources, artifacts }); ok = true; } catch {}
      if (!ok) {
        try { setFinalAnswer({ answer: (answer || "[leer]"), sources, artifacts }); ok = true; } catch {}
      }
      if (!ok) {
        const el = document.querySelector('#final-answer');
        if (el) el.textContent = (answer || "[leer]");
      }
    } catch (e) {
      console.error("Final rendering failed", e);
      try { setFinalAnswer("[leer]"); } catch {}
    }
  }

  // Poller: immer starten – unabhängig von SSE
  (async () => {
    try {
      const parsed = await waitForResult(resultUrl);
      await renderFinal(parsed);
    } catch (e) {
      console.error("waitForResult failed", e);
    }
  })();

  async function completeNow(){
    try { await renderFinal(); } catch (e) { console.error("completeNow()", e); }
  }
}
