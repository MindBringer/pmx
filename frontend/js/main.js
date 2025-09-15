// ==============================
// File: frontend/main.js
// Refactor: nutzt zentrale Renderer (ui/renderers.js)
// Enthält: API-Key-Handling, Fetch-Patch, Prompt-/Meeting-Forms,
//          Mic-Recording-Helpers, Tab-Guard
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

// ---------- Boot ----------
initTabs();
renderConvStatus();
initDocsUpload();
initAudioUpload();
initSpeakers();

// ---------- API Key handling (RAG) ----------
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

// ---------- Fetch wrapper: add x-api-key for same-origin ----------
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

// ---------- Prompt / Fragen ----------
const promptForm = document.getElementById('prompt-form');
promptForm?.addEventListener('submit', async (e) => {
  e.preventDefault();

  const resultDiv = document.getElementById('result');
  const resultOut = document.getElementById('result-output');
  const spinner   = document.getElementById('spinner');
  const submitBtn = document.getElementById('submit-btn');

  const prompt = (document.getElementById('prompt')?.value || '').trim();
  const system = (document.getElementById('input-sys')?.value || '').trim();
  const model  = (document.getElementById('model_sys')?.value || '').trim() || (document.getElementById('model_usr')?.value || '').trim();

  let ragVal = '';
  const ragChoices = document.getElementById('rag-choices');
  if (ragChoices){
    const checked = ragChoices.querySelector('input[type="radio"]:checked');
    ragVal = checked?.value || ragChoices.value || '';
  }

  if (!prompt){
    if (resultOut) resultOut.textContent = "⚠️ Bitte gib einen Prompt ein.";
    if (resultDiv) resultDiv.className = "error";
    return;
  }

  if (resultOut) resultOut.innerHTML = "";
  if (resultDiv) resultDiv.className = "";
  const hideSpinner = showFor(spinner, 300);
  if (submitBtn) submitBtn.disabled = true;

  try {
    const isAgents = activeSubtab?.()==='subtab-agents';
    const payload = { prompt, system, rag: ragVal };

    if (isAgents){
      const personas = (typeof collectPersonas === 'function') ? collectPersonas() : [];
      if (personas && personas.length){
        payload.personas = personas;

        // optional agent rounds
        const roundsEl = document.getElementById("agent_rounds");
        const roundsVal = Number(roundsEl?.value || 1);
        if (Number.isFinite(roundsVal) && roundsVal >= 1) {
          payload.agent_rounds = Math.max(1, Math.min(10, Math.round(roundsVal)));
        }

        // critic/writer models (optional)
        const criticProv = document.getElementById("critic_provider")?.value || "";
        const criticModel = (document.getElementById("critic_model")?.value || "").trim();
        if (criticProv || criticModel) payload.critic = { provider: criticProv || undefined, model: criticModel || undefined };
        const wProv = document.getElementById('writer_provider')?.value || '';
        const wModel = (document.getElementById('writer_model')?.value || '').trim();
        if (wProv || wModel) payload.writer = { provider: wProv || undefined, model: wModel || undefined };

        // pass key explicitly as body field as well (helps if backend expects it in JSON)
        const key = getRagApiKey();
        if (key) payload.api_key = key;

        // Hinweis: Live-Zwischenstände erfolgen in features/agents.js via renderers.appendIntermediate()
        await startAsyncRun('Personas', payload);
        return;
      }
    }

    payload.model = model;
    const key = getRagApiKey();
    if (key) payload.api_key = key;
    await startSyncRun('Frage', payload);
  } catch (err){
    setError(err?.message || String(err));
  } finally {
    hideSpinner();
    if (submitBtn) submitBtn.disabled = false;
  }
});

// ---------- Meeting: Besprechungen & Audio ----------
(function(){
  const meetingForm = document.getElementById("meeting-form");
  if (!meetingForm) return;

  // Fixed webhook per your spec
  const MEETING_WEBHOOK = "https://ai.intern/webhook/meetings/summarize";

  const meetingFile   = document.getElementById("meetingFile");
  const diarEl        = document.getElementById("meetDiarize");
  const identEl       = document.getElementById("meetIdentify");
  const hintsEl       = document.getElementById("meetSpeakerHints");
  const mStartBtn     = document.getElementById("micStartMeet");
  const mStopBtn      = document.getElementById("micStopMeet");
  const mCheckBtn     = document.getElementById("micCheckMeet");
  const mSel          = document.getElementById("micSelectMeet");
  const mStatus       = document.getElementById("micStatusMeet");
  const mMeter        = document.getElementById("micMeterMeet");
  const mTimer        = document.getElementById("micTimerMeet");

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
    if (mStartBtn) mStartBtn.disabled = true; if (mStopBtn) mStopBtn.disabled  = false;
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
        if (meetingFile) meetingFile.files = dt.files;
        if (mStatus) mStatus.textContent = 'Aufnahme übernommen.';
      } catch {}
      try { mic.stream.getTracks().forEach(t=>t.stop()); } catch {}
      if (mStartBtn) mStartBtn.disabled = false; if (mStopBtn) mStopBtn.disabled  = true;
    };
    mic.rec.start(1000);
    if (mStatus) mStatus.textContent = 'Aufnahme läuft...';
  }
  function stopRecording(){ try { mic.rec?.stop(); } catch {} }

  mCheckBtn?.addEventListener('click', listMics);
  mStartBtn?.addEventListener('click', startRecording);
  mStopBtn?.addEventListener('click', stopRecording);
  if (mSel) listMics();

  meetingForm.addEventListener('submit', async (e)=>{
    e.preventDefault();

    const resultDiv = document.getElementById('result');
    const resultOut = document.getElementById('result-output');
    const spinner   = document.getElementById('spinner');
    if (resultOut) resultOut.innerHTML = "";
    if (resultDiv) resultDiv.className = "";
    const hideSpinner = showFor(spinner, 300);

    try {
      const file = meetingFile?.files?.[0];
      if (!file) throw new Error("Bitte eine Audio-Datei auswählen oder aufnehmen.");
      const ok = await isPlayableAudio(file);
      if (!ok) throw new Error("Die ausgewählte Datei konnte nicht geprüft werden (kein abspielbares Audio).");

      const fd = new FormData();
      fd.append('file', file);
      if (diarEl)  fd.append('diarize_flag', diarEl.checked ? 'true' : 'false');
      if (identEl) fd.append('identify', identEl.checked ? 'true' : 'false');
      if (hintsEl && hintsEl.value.trim()) fd.append('speaker_hints', hintsEl.value.trim());

      const resp = await fetch(MEETING_WEBHOOK, { method:'POST', body: fd });
      const raw  = await resp.text();
      if (!resp.ok) throw new Error(raw || `Fehler ${resp.status}`);

      let data = null; try { data = JSON.parse(raw); } catch {}

      setMeetingResult({
        summary:   data?.summary || data?.result?.summary || data?.answer || data?.text || "",
        actions:   data?.action_items || data?.result?.action_items || data?.todos || [],
        decisions: data?.decisions || data?.result?.decisions || [],
        speakers:  data?.speakers || data?.result?.speakers || [],
        sources:   data?.sources || data?.documents || [],
        raw:       data || raw
      });
    } catch (err){
      setError(err?.message || String(err));
    } finally {
      hideSpinner();
    }
  });
})();

// ---------- Strict Tab Guard (fallback) ----------
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


// ==============================
// File: frontend/ui/renderers.js
// Zentrale Rendering-Schicht + Live-Zwischenstände (SSE)
// ==============================

import { escapeHtml, asText } from "../utils/format.js";

// --- DOM refs (defensiv) ---
const jobBox     = document.getElementById('job-status');
const jobTitleEl = document.getElementById('job-title');
const jobLine    = document.getElementById('job-statusline');
const jobLog     = document.getElementById('job-log');

const resultDiv  = document.getElementById("result");
const resultOut  = document.getElementById("result-output");

// Ensure a timeline container for intermediate chunks
function ensureTimeline(){
  if (!resultOut) return null;
  let tl = resultOut.querySelector('#result-timeline');
  if (!tl){
    tl = document.createElement('div');
    tl.id = 'result-timeline';
    tl.style.marginTop = '8px';
    resultOut.appendChild(tl);
  }
  return tl;
}

export function showJob(title){
  if (jobBox) jobBox.style.display = 'block';
  if (jobTitleEl) jobTitleEl.textContent = title || 'Agentenlauf';
  if (jobLine) jobLine.textContent  = 'Gestartet …';
  if (jobLog) jobLog.innerHTML     = '';
}

export function updateJobStatus(text){
  if (jobLine) jobLine.textContent = String(text ?? '');
}

export function logJob(msg){
  if (!jobLog) return;
  const div = document.createElement('div');
  div.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
  jobLog.appendChild(div);
  jobLog.scrollTop = jobLog.scrollHeight;
}

export function sseLabel(jobTitle, evt){
  const parts = [];
  if (jobTitle) parts.push(jobTitle);
  if (evt?.persona) parts.push(evt.persona);
  if (evt?.role) parts.push('/'+evt.role);
  if (evt?.round && evt?.rounds_total) parts.push(` – Runde ${evt.round}/${evt.rounds_total}`);
  return parts.join(' ');
}

export function renderSources(sources){
  try {
    const arr = Array.isArray(sources) ? sources : [];
    if (!arr.length) return '';
    let html = `<div style="margin-top:12px;font-weight:700">Quellen</div><ul>`;
    html += arr.map((s,i)=>{
      if (typeof s === "string") return `<li>${escapeHtml(s)}</li>`;
      const title = escapeHtml(String(s.title || s.name || s.id || `Quelle ${i+1}`));
      const meta  = escapeHtml(String(s.meta || s.metadata || s.tags || ''));
      const url   = s.url ? `<a href="${escapeHtml(String(s.url))}" target="_blank" rel="noopener">Link</a>` : '';
      const snippet = escapeHtml(String(s.snippet || s.content || s.text || ''));
      return `<li><b>${title}</b>${meta?` – <span class="muted">${meta}</span>`:''} ${url}${snippet?`<div class="inline-help" style="margin-top:4px">${snippet}</div>`:''}</li>`;
    }).join('');
    html += `</ul>`;
    return html;
  } catch { return ''; }
}
