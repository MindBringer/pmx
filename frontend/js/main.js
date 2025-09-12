
import { initTabs, activeSubtab } from "./ui/tabs.js";
import { showFor } from "./utils/dom.js";
import { startSyncRun } from "./features/syncChat.js";
import { startAsyncRun, collectPersonas } from "./features/agents.js";
import { initDocsUpload } from "./features/docs.js";
import { initAudioUpload } from "./features/audio.js";
import { initSpeakers } from "./features/speakers.js";
import { renderConvStatus } from "./state/conversation.js";

initTabs();
renderConvStatus();
initDocsUpload();
initAudioUpload();
initSpeakers();

const apiKeyInput = document.getElementById('apiKey');
const toggleKeyBtn = document.getElementById('toggleKey');
const savedKey = localStorage.getItem('ragApiKey');
if (savedKey) apiKeyInput.value = savedKey;
apiKeyInput?.addEventListener('input', () => {
  localStorage.setItem('ragApiKey', apiKeyInput.value.trim());
});
toggleKeyBtn?.addEventListener('click', () => {
  const hidden = apiKeyInput.type === 'password';
  apiKeyInput.type = hidden ? 'text' : 'password';
  toggleKeyBtn.textContent = hidden ? '🙈' : '👁️';
});

const ragChoices = document.getElementById('rag-choices');
ragChoices?.addEventListener('change', () => {
  ragChoices.querySelectorAll('.choice').forEach(c => c.classList.remove('active'));
  const sel = ragChoices.querySelector('input[name="rag"]:checked');
  sel?.parentElement?.classList.add('active');
});

const form      = document.getElementById("prompt-form");
const spinner   = document.getElementById("spinner");
const submitBtn = document.getElementById("submit-btn");
const resultDiv = document.getElementById("result");
const resultOut = document.getElementById("result-output");

form?.addEventListener("submit", async (e)=>{
  e.preventDefault();
  const prompt = document.getElementById("prompt").value.trim();
  const model  = document.getElementById("model_sys").value;
  const system = document.getElementById("system").value.trim();
  const ragVal = document.querySelector('input[name="rag"]:checked')?.value === "true";

  if (!prompt) {
    resultOut.textContent = "⚠️ Bitte gib einen Prompt ein.";
    resultDiv.className = "error";
    return;
  }

  resultOut.innerHTML = "";
  resultDiv.className = "";
  const hideSpinner = showFor(spinner, 300);
  if (submitBtn) submitBtn.disabled = true;

  try {
    const isAgents = activeSubtab()==='subtab-agents';
    const payload = { prompt, system, rag: ragVal };

    if (isAgents){
      const personas = collectPersonas();
      if (personas.length){
        payload.personas = personas;
        const roundsEl = document.getElementById("agent_rounds");
        const roundsVal = Number(roundsEl?.value || 1);
        if (Number.isFinite(roundsVal) && roundsVal >= 1) {
          payload.agent_rounds = Math.max(1, Math.min(10, Math.round(roundsVal)));
        }
        const criticProv = document.getElementById("critic_provider")?.value || "";
        const criticModel = (document.getElementById("critic_model")?.value || "").trim();
        if (criticProv || criticModel) payload.critic = { provider: criticProv || undefined, model: criticModel || undefined };
        const wProv = document.getElementById('writer_provider')?.value || '';
        const wModel = (document.getElementById('writer_model')?.value || '').trim();
        if (wProv || wModel) payload.writer = { provider: wProv || undefined, model: wModel || undefined };
        const title = personas.map(p=>p.label||'Persona').slice(0,3).join(', ') || prompt.split('\n')[0].slice(0,80);
        hideSpinner();
        await startAsyncRun(title || 'Agentenlauf', payload);
        return;
      }
    }

    payload.model = model;
    await startSyncRun('Frage', payload);
  } catch (err){
    resultOut.textContent = `❌ Fehler: ${err.message}`;
    resultDiv.className = "error";
  } finally {
    hideSpinner();
    if (submitBtn) submitBtn.disabled = false;
  }
});


// --- initMeetingTab: Besprechungen & Audio ---
(function initMeetingTab(){
  const form = document.getElementById("meeting-form");
  if (!form) return;

  const fileInput = document.getElementById("meetingFile");
  const hookEl = document.getElementById("meetingWebhook");
  const diarEl = document.getElementById("meetDiarize");
  const identEl = document.getElementById("meetIdentify");
  const hintsEl = document.getElementById("meetSpeakerHints");

  // mic stuff
  const micSel = document.getElementById("micSelectMeet");
  const micStatus = document.getElementById("micStatusMeet");
  const micMeter = document.getElementById("micMeterMeet");
  const micTimer = document.getElementById("micTimerMeet");
  const btnCheck = document.getElementById("micCheckMeet");
  const btnStart = document.getElementById("micStartMeet");
  const btnStop  = document.getElementById("micStopMeet");

  // result box (global, wie bei Fragen)
  const resultDiv = document.getElementById("result");
  const resultOut = document.getElementById("result-output");
  const spinner   = document.getElementById("spinner");

  // Persist webhook URL
  try {
    const saved = localStorage.getItem('meetingWebhookUrl');
    if (saved && hookEl) hookEl.value = saved;
    hookEl?.addEventListener('input', ()=>{
      localStorage.setItem('meetingWebhookUrl', hookEl.value.trim());
    });
  } catch {}

  function getWebhook(){
    const v = (hookEl?.value || "").trim();
    return v || "/webhook/meeting/summary";
  }

  // Mic device list
  async function listMics(){
    try {
      await navigator.mediaDevices.getUserMedia({audio:true});
      const devs = await navigator.mediaDevices.enumerateDevices();
      const mics = devs.filter(d=>d.kind === 'audioinput');
      micSel.innerHTML = "";
      for (const d of mics){
        const opt = document.createElement('option');
        opt.value = d.deviceId;
        opt.textContent = d.label || ('Mikrofon ' + (micSel.length+1));
        micSel.appendChild(opt);
      }
      if (!mics.length) micStatus.textContent = "Kein Mikro gefunden.";
      else micStatus.textContent = `Geräte: ${mics.length}`;
    } catch (err){
      micStatus.textContent = 'Zugriff verweigert? ' + err.message;
    }
  }

  const mic = { rec:null, stream:null, chunks:[], ctx:null, analyser:null, raf:0, startTs:0 };
  function stopMeter(){
    if (mic.raf) cancelAnimationFrame(mic.raf);
    mic.raf = 0;
    if (micMeter) micMeter.style.width = "0%";
  }
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
        let peak = 0; for (let i=0;i<data.length;i++){ peak = Math.max(peak, Math.abs(data[i]-128)); }
        const pct = Math.min(100, Math.round((peak/128)*100));
        if (micMeter) micMeter.style.width = pct + '%';
        if (micTimer && mic.startTs){
          const s = Math.floor((Date.now()-mic.startTs)/1000);
          micTimer.textContent = String(Math.floor(s/60)).padStart(2,'0') + ':' + String(s%60).padStart(2,'0');
        }
      })();
    } catch {}
  }

  async function startRec(){
    btnStart.disabled = true;
    btnStop.disabled  = false;
    const deviceId = micSel?.value;
    mic.stream = await navigator.mediaDevices.getUserMedia({ audio: deviceId ? {deviceId:{exact:deviceId}} : true });
    runMeter(mic.stream);
    mic.startTs = Date.now();
    mic.chunks = [];
    mic.rec = new MediaRecorder(mic.stream, { mimeType: 'audio/webm;codecs=opus' });
    mic.rec.ondataavailable = (e)=>{ if (e.data?.size) mic.chunks.push(e.data); };
    mic.rec.onstop = async ()=>{
      stopMeter();
      const blob = new Blob(mic.chunks, { type: 'audio/webm' });
      try {
        const dt = new DataTransfer();
        const f = new File([blob], 'aufnahme.webm', { type: 'audio/webm' });
        dt.items.add(f);
        fileInput.files = dt.files;
        micStatus.textContent = 'Aufnahme übernommen.';
      } catch {}
      try { mic.stream.getTracks().forEach(t=>t.stop()); } catch {}
      btnStart.disabled = false;
      btnStop.disabled  = true;
    };
    mic.rec.start(1000);
    micStatus.textContent = 'Aufnahme läuft...';
  }
  function stopRec(){
    try { mic.rec?.stop(); } catch {}
  }

  async function isPlayableAudio(file){
    if (!file) return false;
    return await new Promise((resolve)=>{
      try{
        const url = URL.createObjectURL(file);
        const a = document.createElement('audio');
        let timer = setTimeout(()=>{ cleanup(); resolve(false); }, 3000);
        function cleanup(){ try{ URL.revokeObjectURL(url); }catch{}; a.remove(); clearTimeout(timer); }
        a.addEventListener('loadedmetadata', ()=>{ cleanup(); resolve(true); }, {once:true});
        a.addEventListener('error', ()=>{ cleanup(); resolve(false); }, {once:true});
        a.src = url; a.load();
      }catch{ resolve(false); }
    });
  }

  btnCheck?.addEventListener('click', listMics);
  btnStart?.addEventListener('click', startRec);
  btnStop?.addEventListener('click', stopRec);

  // Pre-fill mic device list lazily
  if (micSel) listMics();

  form.addEventListener('submit', async (e)=>{
    e.preventDefault();
    resultOut.innerHTML = "";
    resultDiv.className = "";
    const hideSpinner = (()=>{ spinner.style.display=''; return ()=>{spinner.style.display='none';}; })();

    try {
      const file = fileInput?.files?.[0];
      if (!file) throw new Error('Bitte eine Audio-Datei auswählen oder aufnehmen.');
      const ok = await isPlayableAudio(file);
      if (!ok) throw new Error('Kein abspielbares Audio erkannt.');

      const fd = new FormData();
      fd.append('file', file);
      if (diarEl)  fd.append('diarize_flag', diarEl.checked ? 'true' : 'false');
      if (identEl) fd.append('identify', identEl.checked ? 'true' : 'false');
      if (hintsEl && hintsEl.value.trim()) fd.append('speaker_hints', hintsEl.value.trim());

      // optional x-api-key übernehmen (aus Dateien-Reiter)
      const apiKey = document.getElementById("apiKey")?.value?.trim();
      const headers = {};
      if (apiKey) headers['x-api-key'] = apiKey;

      const resp = await fetch(getWebhook(), { method:'POST', headers, body: fd });
      const raw = await resp.text();
      if (!resp.ok) throw new Error(raw || `Fehler ${resp.status}`);

      let data = null; try { data = JSON.parse(raw); } catch {}
      const summary = data?.summary || data?.result?.summary || data?.answer || data?.text || "";
      const actions = data?.action_items || data?.result?.action_items || data?.todos || [];
      const decisions = data?.decisions || data?.result?.decisions || [];
      const speakers = data?.speakers || data?.result?.speakers || [];
      const sources  = data?.sources || data?.documents || [];

      let html = "";
      if (summary){
        html += `<div style="display:flex;align-items:center;justify-content:space-between;gap:8px">
                  <div>✅ Fertig – Sitzungszusammenfassung:</div>
                  <button type="button" id="copy-answer" class="secondary" style="width:auto">kopieren</button>
                </div>`;
        html += `<pre id="answer-pre" class="prewrap mono" style="margin-top:6px;"></pre>`;
      } else {
        html += `<div>✅ Ergebnis empfangen.</div>`;
        html += `<pre class="prewrap mono" style="margin-top:6px;">${(raw||"").replace(/[&<>]/g, s=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[s]))}</pre>`;
      }

      if (Array.isArray(actions) && actions.length){
        html += `<div style="margin-top:10px;font-weight:700">To-Dos</div><ul>` +
                actions.map(a=>`<li>${String(a?.title||a)}</li>`).join('') + `</ul>`;
      }
      if (Array.isArray(decisions) && decisions.length){
        html += `<div style="margin-top:10px;font-weight:700">Entscheidungen</div><ul>` +
                decisions.map(a=>`<li>${String(a?.title||a)}</li>`).join('') + `</ul>`;
      }
      if (Array.isArray(speakers) && speakers.length){
        html += `<div style="margin-top:10px;font-weight:700">Erkannte Sprecher</div><ul>` +
                speakers.map(s=>`<li>${String(s?.name||s)}</li>`).join('') + `</ul>`;
      }
      resultOut.innerHTML = html;
      const pre = document.getElementById('answer-pre');
      if (pre) pre.textContent = String(summary || (data ? JSON.stringify(data, null, 2) : raw));
      document.getElementById('copy-answer')?.addEventListener('click', ()=>{
        const txt = pre?.textContent || "";
        navigator.clipboard.writeText(txt);
      });
      resultDiv.className = "success";
    } catch (err){
      resultOut.textContent = `❌ Fehler: ${err.message}`;
      resultDiv.className = "error";
    } finally {
      hideSpinner();
    }
  });
})();

// --- Safe activator for the 'Besprechungen & Audio' tab (works even if existing tabs.js ignores new button)
(function activateMeetTabFallback(){
  const meetBtn = document.querySelector('.tab[data-target="tab-meet"]');
  const meetPanel = document.getElementById('tab-meet');
  if (!meetBtn || !meetPanel) return;
  // If clicking the button doesn't switch (some tab libs block), we enforce our own toggle.
  meetBtn.addEventListener('click', (ev)=>{
    // If a different handler already activated it, do nothing
    if (meetPanel.classList.contains('active')) return;
    document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active'));
    meetBtn.classList.add('active');
    document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
    meetPanel.classList.add('active');
  });
})();

