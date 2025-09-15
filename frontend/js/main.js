
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


// === Meeting: Besprechungen & Audio ===
(function(){
  const meetingForm   = document.getElementById("meeting-form");
  if (!meetingForm) return;

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

  function showFor(el, ms){ if(!el) return ()=>{}; el.style.display=''; let to=setTimeout(()=>el.style.display='none', ms); return ()=>{clearTimeout(to); el.style.display='none'}; }

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

  const mic = { rec:null, stream:null, chunks:[], ctx:null, analyser:null, raf:0, startTs:0 };
  function stopMeter(){ if (mic.raf) cancelAnimationFrame(mic.raf); mic.raf=0; if (mMeter) mMeter.style.width='0%'; }
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
          mTimer.textContent = String(Math.floor(s/60)).padStart(2,'0') + ':' + String(s%60).padStart(2,'0');
        }
      })();
    } catch {}
  }
  async function listMics(){
    try {
      await navigator.mediaDevices.getUserMedia({audio:true});
      const devs = await navigator.mediaDevices.enumerateDevices();
      const mics = devs.filter(d=>d.kind==='audioinput');
      mSel.innerHTML = "";
      for (const d of mics){
        const opt = document.createElement('option');
        opt.value = d.deviceId;
        opt.textContent = d.label || ('Mikrofon ' + (mSel.length+1));
        mSel.appendChild(opt);
      }
      mStatus.textContent = mics.length ? `Geräte: ${mics.length}` : "Kein Mikro gefunden.";
    } catch (err){
      mStatus.textContent = 'Zugriff verweigert? ' + err.message;
    }
  }
  async function startRecording(){
    mStartBtn.disabled = true; mStopBtn.disabled = false;
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
        meetingFile.files = dt.files;
        mStatus.textContent = 'Aufnahme übernommen.';
      } catch {}
      try { mic.stream.getTracks().forEach(t=>t.stop()); } catch {}
      mStartBtn.disabled = false; mStopBtn.disabled = true;
    };
    mic.rec.start(1000);
    mStatus.textContent = 'Aufnahme läuft...';
  }
  function stopRecording(){ try{ mic.rec?.stop(); }catch{} }

  mCheckBtn?.addEventListener('click', listMics);
  mStartBtn?.addEventListener('click', startRecording);
  mStopBtn?.addEventListener('click', stopRecording);
  if (mSel) listMics();

  meetingForm.addEventListener('submit', async (e)=>{
    e.preventDefault();
    const file = meetingFile?.files?.[0];

    const resultDiv = document.getElementById('result');
    const resultOut = document.getElementById('result-output');
    const spinner   = document.getElementById('spinner');
    resultOut.innerHTML = ""; resultDiv.className = "";
    const hideSpinner = showFor(spinner, 300);

    try {
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

      let data = null, html = "";
      try { data = JSON.parse(raw); } catch {}

      const summary = data?.summary || data?.result?.summary || data?.answer || data?.text || "";
      const actions = data?.action_items || data?.result?.action_items || data?.todos || [];
      const decisions = data?.decisions || data?.result?.decisions || [];
      const speakers = data?.speakers || data?.result?.speakers || [];
      const sources  = data?.sources || data?.documents || [];

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

      try { if (typeof renderSources === 'function') html += renderSources(sources); } catch {}

      resultOut.innerHTML = html;
      const pre = document.getElementById('answer-pre');
      if (pre) pre.textContent = String(summary || (data ? JSON.stringify(data, null, 2) : raw));
      document.getElementById('copy-answer')?.addEventListener('click', ()=> navigator.clipboard.writeText(pre?.textContent||""));
      resultDiv.className = "success";
    } catch (err){
      resultOut.textContent = `❌ Fehler: ${err.message}`;
      resultDiv.className = "error";
    } finally {
      hideSpinner();
    }
  });
})();

