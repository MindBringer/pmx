// ==============================
// File: frontend/main.js (updated)
// ==============================

import { initTabs, activeSubtab } from "./ui/tabs.js";
import { showFor } from "./utils/dom.js";
import { startSyncRun } from "./features/syncChat.js";
import { startAsyncRun, collectPersonas } from "./features/agents.js";
import { initDocsUpload } from "./features/docs.js";
import { initAudioUpload } from "./features/audio.js";
import { initSpeakers } from "./features/speakers.js";
import { renderConvStatus } from "./state/conversation.js";
import {
  showJob,
  logJob,
  setFinalAnswer,
  setError,
  renderSources,
  setMeetingResult,
} from "./ui/renderers.js";

/* -------------------------------------------
   Mirror-Helpers: halten beide Tabs synchron
   ------------------------------------------- */
function setDualHTML(idA, idB, html = "") {
  const a = document.getElementById(idA);
  const b = document.getElementById(idB);
  if (a) a.innerHTML = html;
  if (b) b.innerHTML = html;
}
function setDualText(idA, idB, text = "") {
  const a = document.getElementById(idA);
  const b = document.getElementById(idB);
  if (a) a.textContent = text;
  if (b) b.textContent = text;
}
function setDualDisplay(idA, idB, show) {
  const a = document.getElementById(idA);
  const b = document.getElementById(idB);
  const val = show ? "block" : "none";
  if (a) a.style.display = val;
  if (b) b.style.display = val;
}

// Spiegel für Spinner (Fragen + Docs)
function showSpinnerDual(ms = 300) {
  const s1 = document.getElementById("spinner");
  const s2 = document.getElementById("spinner-docs");
  const hide1 = showFor(s1, ms);
  const hide2 = showFor(s2, ms);
  return () => { hide1(); hide2(); };
}

// Spiegel für Live-Status (Titel/Zeile/Log)
function showJobDual(title = "—") {
  setDualDisplay("job-status", "job-status-docs", true);
  setDualText("job-title", "job-title-docs", title);
}
function setJobLineDual(line = "") {
  setDualText("job-statusline", "job-statusline-docs", line);
}
function appendJobLogDual(line = "") {
  const a = document.getElementById("job-log");
  const b = document.getElementById("job-log-docs");
  const add = (el) => { if (el) el.textContent += (line.endsWith("\n") ? line : line + "\n"); };
  add(a); add(b);
}
function hideJobDual() {
  setDualDisplay("job-status", "job-status-docs", false);
}

/* Optional: kleine Proxy-Hooks, falls Renderers bereits schreiben */
(function attachRenderMirrors(){
  // Antwort spiegeln (wenn setFinalAnswer den Standard-Output nutzt)
  const ro = document.getElementById("result-output");
  if (ro) {
    const obs = new MutationObserver(() => {
      const html = ro.innerHTML;
      setDualHTML("result-output", "result-output-docs", html);
    });
    obs.observe(ro, { childList: true, subtree: true, characterData: true });
  }

  // Live-Status spiegeln
  const jt = document.getElementById("job-title");
  const jl = document.getElementById("job-statusline");
  const jlog = document.getElementById("job-log");
  if (jt) new MutationObserver(() => setDualText("job-title","job-title-docs", jt.textContent)).observe(jt, { childList:true, characterData:true, subtree:true });
  if (jl) new MutationObserver(() => setDualText("job-statusline","job-statusline-docs", jl.textContent)).observe(jl, { childList:true, characterData:true, subtree:true });
  if (jlog) new MutationObserver(() => setDualText("job-log","job-log-docs", jlog.textContent)).observe(jlog, { childList:true, characterData:true, subtree:true });
})();

/* -------------------------------------------
   Boot
   ------------------------------------------- */
initTabs();
renderConvStatus();
initDocsUpload();   // lässt dein bestehendes Upload-Handling weiterlaufen
initAudioUpload();  // belasse es; unten ergänzen wir expliziten Submit-Handler
initSpeakers();     // bestehende Logik bleibt; unten ergänzen wir Dual-Render

/* -------------------------------------------
   API Key handling (RAG)
   ------------------------------------------- */
const apiKeyInput = document.getElementById('apiKey');
const toggleKeyBtn = document.getElementById('toggleKey');
try {
  const savedKey = localStorage.getItem('ragApiKey');
  if (savedKey && apiKeyInput) apiKeyInput.value = savedKey;
} catch {}
apiKeyInput?.addEventListener('input', () => {
  const v = apiKeyInput.value.trim();
  try { localStorage.setItem('ragApiKey', v); } catch {}
});
toggleKeyBtn?.addEventListener('click', () => {
  const hidden = apiKeyInput.type === 'password';
  apiKeyInput.type = hidden ? 'text' : 'password';
  toggleKeyBtn.textContent = hidden ? '🙈' : '👁️';
});

function getRagApiKey(){
  return (apiKeyInput?.value || '').trim() || (localStorage.getItem('ragApiKey')||'').trim();
}
window.getRagApiKey = getRagApiKey;

/* -------------------------------------------
   Fetch wrapper: add x-api-key for same-origin
   ------------------------------------------- */
(function patchFetchForApiKey(){
  const orig = window.fetch;
  window.fetch = async function(input, init){
    try{
      const url = (typeof input === 'string') ? input : (input?.url || '');
      const sameOrigin = url.startsWith('/') || url.startsWith(location.origin);
      if (sameOrigin){
        init = init || {};
        const headers = new Headers(init.headers || {});
        const key = getRagApiKey();
        if (key && !headers.has('x-api-key')) headers.set('x-api-key', key);
        init.headers = headers;
      }
    } catch {}
    return orig(input, init);
  };
})();

/* -------------------------------------------
   Prompt / Fragen
   ------------------------------------------- */
const promptForm = document.getElementById('prompt-form');
promptForm?.addEventListener('submit', async (e) => {
  e.preventDefault();

  const prompt = (document.getElementById('prompt')?.value || '').trim();
  const system = (document.getElementById('system')?.value || '').trim(); // ID fix
  const model  = (document.getElementById('model_sys')?.value || '').trim() || (document.getElementById('model_usr')?.value || '').trim();

  let ragVal = '';
  const ragChoices = document.getElementById('rag-choices');
  if (ragChoices){
    const checked = ragChoices.querySelector('input[type="radio"]:checked');
    ragVal = checked?.value || ragChoices.value || '';
  }

  if (!prompt){
    setDualText('result-output','result-output-docs',"⚠️ Bitte gib einen Prompt ein.");
    return;
  }

  const hideSpinner = showSpinnerDual(300);
  const submitBtn = document.getElementById('submit-btn');
  if (submitBtn) submitBtn.disabled = true;

  try {
    const isAgents = activeSubtab?.()==='subtab-agents';
    const payload = { prompt, system, rag: ragVal };

    if (isAgents){
      const personas = (typeof collectPersonas === 'function') ? collectPersonas() : [];
      if (personas && personas.length){
        payload.personas = personas;

        // agent rounds
        const roundsEl = document.getElementById("agent_rounds");
        const roundsVal = Number(roundsEl?.value || 1);
        if (Number.isFinite(roundsVal) && roundsVal >= 1) {
          payload.agent_rounds = Math.max(1, Math.min(10, Math.round(roundsVal)));
        }

        // critic/writer (optional)
        const criticProv = document.getElementById("critic_provider")?.value || "";
        const criticModel = (document.getElementById("critic_model")?.value || "").trim();
        if (criticProv || criticModel) payload.critic = { provider: criticProv || undefined, model: criticModel || undefined };
        const wProv = document.getElementById('writer_provider')?.value || '';
        const wModel = (document.getElementById('writer_model')?.value || '').trim();
        if (wProv || wModel) payload.writer = { provider: wProv || undefined, model: wModel || undefined };

        const key = getRagApiKey();
        if (key) payload.api_key = key;

        // Live-Status sichtbar auf beiden Tabs
        showJobDual('Personas');
        setJobLineDual('Starte Agenten …');

        await startAsyncRun('Personas', payload);

        // Abschluss-Status ausblenden
        hideJobDual();
        return;
      }
    }

    payload.model = model;
    const key = getRagApiKey();
    if (key) payload.api_key = key;

    showJobDual('Frage');
    setJobLineDual('Starte Anfrage …');

    await startSyncRun('Frage', payload);

    hideJobDual();
  } catch (err){
    setError(err?.message || String(err));
  } finally {
    hideSpinner();
    if (submitBtn) submitBtn.disabled = false;
  }
});

/* -------------------------------------------
   Dateien & Audio – Audio Submit + Mic (Transcribe)
   ------------------------------------------- */

// Fixer Webhook für Meetings/Audio-Zusammenfassung
const MEETING_WEBHOOK = "https://ai.intern/webhook/meetings/summarize";

(function audioSection(){
  const audioForm     = document.getElementById("audio-form");
  if (!audioForm) return;

  const audioFile     = document.getElementById("audioFile");
  const diarEl        = document.getElementById("doDiar");
  const identEl       = document.getElementById("doIdentify");
  const hintsEl       = document.getElementById("speakerHints");
  const tagsEl        = document.getElementById("audioTags");
  const modelEl       = document.getElementById("audioModel");
  const sumEl         = document.getElementById("audioSummarize");

  // Mic controls (Transcribe)
  const mSel   = document.getElementById("micSelectTrans");
  const mStart = document.getElementById("micStartTrans");
  const mStop  = document.getElementById("micStopTrans");
  const mCheck = document.getElementById("micCheckTrans");
  const mStatus= document.getElementById("micStatusTrans");
  const mMeter = document.getElementById("micMeterTrans");
  const mTimer = document.getElementById("micTimerTrans");

  async function isPlayableAudio(file, timeoutMs=3000){
    if (!file || !(file instanceof Blob)) return false;
    return await new Promise((resolve)=>{
      try{
        const url = URL.createObjectURL(file);
        const a = document.createElement('audio');
        let timer = setTimeout(()=>{ cleanup(); resolve(false); }, timeoutMs);
        function cleanup(){ try{ URL.revokeObjectURL(url); }catch{}; a.remove(); clearTimeout(timer); }
        a.addEventListener('loadedmetadata', ()=>{ cleanup(); resolve(true); }, {once:true});
        a.addEventListener('error', ()=>{ cleanup(); resolve(false); }, {once:true});
        a.src = url; a.load();
      }catch{ resolve(false); }
    });
  }

  // Mic helpers
  const mic = { rec:null, stream:null, chunks:[], ctx:null, analyser:null, raf:0, startTs:0 };
  function stopMeter(){ if (mic.raf) cancelAnimationFrame(mic.raf); mic.raf = 0; if (mMeter) mMeter.style.width = "0%"; }
  function runMeter(stream){
    try {
      mic.ctx = new (window.AudioContext||window.webkitAudioContext)();
      const src = mic.ctx.createMediaStreamSource(stream);
      mic.analyser = mic.ctx.createAnalyser();
      mic.analyser.fftSize = 512;
      src.connect(mic.analyser);
      const data = new Uint8Array(mic.analyser.frequencyBinCount);
      (function tick(){
        mic.raf = requestAnimationFrame(tick);
        mic.analyser.getByteTimeDomainData(data);
        let peak = 0; for (let i=0;i<data.length;i++) peak = Math.max(peak, Math.abs(data[i]-128));
        const pct = Math.min(100, Math.round((peak/128)*100));
        if (mMeter) mMeter.style.width = pct + '%';
        if (mTimer && mic.startTs){
          const s = Math.floor((Date.now()-mic.startTs)/1000);
          const mm = String(Math.floor(s/60)).padStart(2,'0');
          const ss = String(s%60).padStart(2,'0');
          mTimer.textContent = `${mm}:${ss}`;
        }
      })();
    } catch {}
  }
  async function listMics(){
    try {
      await navigator.mediaDevices.getUserMedia({audio:true});
      const devs = await navigator.mediaDevices.enumerateDevices();
      const mics = devs.filter(d=>d.kind==='audioinput');
      if (mSel) mSel.innerHTML = "";
      for (const d of mics){
        const opt = document.createElement('option');
        opt.value = d.deviceId;
        opt.textContent = d.label || ('Mikrofon ' + ((mSel?.length||0)+1));
        mSel?.appendChild(opt);
      }
      if (mStatus) mStatus.textContent = mics.length ? `Geräte: ${mics.length}` : "Kein Mikro gefunden.";
    } catch (err){
      if (mStatus) mStatus.textContent = 'Zugriff verweigert? ' + err.message;
    }
  }
  async function startRecording(){
    if (mStart) mStart.disabled = true; if (mStop) mStop.disabled  = false;
    const deviceId = mSel?.value;
    mic.stream = await navigator.mediaDevices.getUserMedia({ audio: deviceId ? {deviceId:{exact:deviceId}} : true });
    runMeter(mic.stream);
    mic.startTs = Date.now();
    mic.chunks = [];
    mic.rec = new MediaRecorder(mic.stream, { mimeType:'audio/webm;codecs=opus' });
    mic.rec.ondataavailable = (e)=>{ if (e.data?.size) mic.chunks.push(e.data); };
    mic.rec.onstop = async ()=>{
      stopMeter();
      const blob = new Blob(mic.chunks, { type:'audio/webm' });
      try {
        const dt = new DataTransfer();
        const f = new File([blob], 'aufnahme.webm', { type:'audio/webm' });
        dt.items.add(f);
        if (audioFile) audioFile.files = dt.files;
        if (mStatus) mStatus.textContent = 'Aufnahme übernommen.';
      } catch {}
      try { mic.stream.getTracks().forEach(t=>t.stop()); } catch {}
      if (mStart) mStart.disabled = false; if (mStop) mStop.disabled  = true;
    };
    mic.rec.start(1000);
    if (mStatus) mStatus.textContent = 'Aufnahme läuft...';
  }
  function stopRecording(){ try { mic.rec?.stop(); } catch {} }

  mCheck?.addEventListener('click', listMics);
  mStart?.addEventListener('click', startRecording);
  mStop?.addEventListener('click', stopRecording);
  if (mSel) listMics();

 // Audio Submit (robust, CORS-safe, Timeout, dual UI)
audioForm.addEventListener('submit', async (e)=>{
  e.preventDefault();

  // 1) Webhook: relative URL (vermeidet CORS/Redirect-Probleme)
  const MEETING_WEBHOOK_REL = "/webhook/meetings/summarize";

  // 2) Spinner & Live-Status *hart* sichtbar (beide Tabs)
  //    -> zusätzlich zur showFor-Logik, um Race-Conditions zu vermeiden
  const s1 = document.getElementById('spinner');
  const s2 = document.getElementById('spinner-docs');
  if (s1) s1.style.display = 'block';
  if (s2) s2.style.display = 'block';

  const hideSpinner = showSpinnerDual(300);
  showJobDual('Audio');
  setJobLineDual('Prüfe Datei …');

  // 3) Timeout via AbortController
  const controller = new AbortController();
  const TIMEOUT_MS = 90_000; // 90s – je nach Dateigröße ggf. anheben
  const tId = setTimeout(() => controller.abort(new Error('Zeitüberschreitung beim Upload')), TIMEOUT_MS);

  try {
    const file = audioFile?.files?.[0];
    if (!file) throw new Error("Bitte eine Audio-Datei auswählen oder aufnehmen.");

    // Optional: kurze Playability-Prüfung (nicht-blockierend, aber frühzeitiger Feedback)
    const ok = await isPlayableAudio(file);
    if (!ok) appendJobLogDual('⚠️ Warnung: Datei nicht als Audio erkannt – fahre dennoch fort.');

    const fd = new FormData();
    fd.append('file', file);
    if (diarEl)  fd.append('diarize_flag', diarEl.checked ? 'true' : 'false');
    if (identEl) fd.append('identify',    identEl.checked ? 'true' : 'false');
    if (hintsEl && hintsEl.value.trim())  fd.append('speaker_hints', hintsEl.value.trim());
    if (tagsEl  && tagsEl.value.trim())   fd.append('tags', tagsEl.value.trim());
    if (sumEl)  fd.append('summarize',    sumEl.checked ? 'true' : 'false');
    if (modelEl && modelEl.value)         fd.append('model', modelEl.value);

    setJobLineDual('Sende an Webhook …');

    // 4) Wichtig: relative URL verwenden (gleiches Origin) + AbortController
    const resp = await fetch(MEETING_WEBHOOK_REL, {
      method: 'POST',
      body: fd,
      signal: controller.signal,
      // Wichtig: KEIN 'Content-Type' manuell setzen bei FormData
      // mode/credentials default halten, damit Same-Origin sauber funktioniert
    });

    // 5) Antwort sicher lesen (json → text fallback)
    let raw = await resp.text();
    if (!resp.ok) {
      // Wenn der Server einen Fehler-Body als JSON geschickt hat, versuchen wir es anzuzeigen
      let errMsg = raw;
      try {
        const j = JSON.parse(raw);
        errMsg = j?.error || j?.message || raw;
      } catch {}
      throw new Error(errMsg || `HTTP ${resp.status}`);
    }

    setJobLineDual('Verarbeite Antwort …');

    let data = null;
    try { data = JSON.parse(raw); } catch { data = null; }

    // 6) UI rendern – auch wenn nur Text ankommt
    const summary   = data?.summary || data?.result?.summary || data?.answer || data?.text || (typeof raw === 'string' ? raw : "");
    const actions   = data?.action_items || data?.result?.action_items || data?.todos || [];
    const decisions = data?.decisions || data?.result?.decisions || [];
    const speakers  = data?.speakers || data?.result?.speakers || [];
    const sources   = data?.sources || data?.documents || [];

    setMeetingResult({
      summary, actions, decisions, speakers, sources, raw: data || raw
    });

    // Sicherstellen: Ausgabe sichtbar in beiden Antwortboxen
    const ro = document.getElementById('result-output');
    const html = ro ? ro.innerHTML : (summary ? `<div>${summary}</div>` : '');
    setDualHTML('result-output', 'result-output-docs', html);

    setJobLineDual('Fertig.');
  } catch (err) {
    // 7) Fehlermeldung sichtbar machen (beide Tabs)
    const msg = (err?.name === 'AbortError')
      ? '⏱️ Upload/Antwort hat zu lange gedauert.'
      : (err?.message || String(err));

    appendJobLogDual(`❌ ${msg}`);
    setError(msg);
  } finally {
    clearTimeout(tId);
    hideJobDual();
    hideSpinner();
    if (s1) s1.style.display = 'none';
    if (s2) s2.style.display = 'none';
  }
});


/* -------------------------------------------
   Speaker-Liste in zwei Tabs laden/refreshen
   ------------------------------------------- */
async function loadSpeakersDual(){
  try{
    const r = await fetch('/speakers');
    const t = await r.text();
    let data = [];
    try { data = JSON.parse(t); } catch {}
    const html = (data || []).map(s => `<div class="tag">${(s.name||s.id||'')}</div>`).join('')
      || '<div class="inline-help">Keine Sprecher gefunden.</div>';

    const targets = [
      document.getElementById('speaker-list-docs'),
      document.getElementById('speaker-list-settings')
    ].filter(Boolean);
    targets.forEach(t => t.innerHTML = html);
  } catch (e) {
    const errHtml = `<div class="inline-help">Fehler beim Laden der Sprecher: ${e?.message||e}</div>`;
    ['speaker-list-docs','speaker-list-settings'].forEach(id=>{
      const el = document.getElementById(id);
      if (el) el.innerHTML = errHtml;
    });
  }
}
document.getElementById('speaker-refresh-btn-docs')?.addEventListener('click', loadSpeakersDual);
document.getElementById('speaker-refresh-btn-settings')?.addEventListener('click', loadSpeakersDual);
// initial einmal laden (wenn die Bereiche im DOM sind)
if (document.getElementById('speaker-list-docs') || document.getElementById('speaker-list-settings')) {
  loadSpeakersDual();
}

/* -------------------------------------------
   Strict Tab Guard (fallback)
   ------------------------------------------- */
(function tabGuard(){
  function forceActivate(id){
    const panel = document.getElementById(id);
    const btn = document.querySelector('.tab[data-target="'+id+'"]');
    if (!panel || !btn) return;
    document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
    panel.classList.add('active');
    document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
  }
  // prevent accidental form submits by tab buttons
  document.querySelectorAll('.tab').forEach(b=>{ try{ b.type = 'button'; }catch{} });
  document.addEventListener('click', (e)=>{
    const btn = e.target.closest('.tab[data-target]');
    if (!btn) return;
    const id = btn.getAttribute('data-target');
    setTimeout(()=>{
      if (!document.querySelector('.panel.active')) forceActivate(id);
    }, 0);
  }, true);
})();

/* -------------------------------------------
   Bonus: öffentliche Helfer, falls gebraucht
   ------------------------------------------- */
window.__uiMirror = {
  showJobDual,
  setJobLineDual,
  appendJobLogDual,
  hideJobDual,
  showSpinnerDual,
};
