
import { fmtTime } from "../utils/format.js";
const mic = { stream:null, rec:null, chunks:[], analyser:null, raf:0, startTs:0 };
function isSecure(){ return location.protocol === 'https:' || location.hostname === 'localhost' || location.hostname === '127.0.0.1'; }
async function checkHardware(statusEl, selectEl){
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia){
    statusEl.textContent = "❌ Kein getUserMedia verfügbar (Browser zu alt?)."; return false;
  }
  if (!isSecure()){
    statusEl.textContent = "❌ Unsichere Seite. Mikrofon benötigt HTTPS oder localhost."; return false;
  }
  try{
    if (navigator.permissions && navigator.permissions.query){
      const p = await navigator.permissions.query({name:'microphone'});
      statusEl.textContent = `Berechtigung: ${p.state}`;
    } else { statusEl.textContent = "Berechtigung: unbekannt"; }
  }catch{}
  await navigator.mediaDevices.getUserMedia({audio:true}).then(s=>s.getTracks().forEach(t=>t.stop())).catch(()=>{});
  const devs = await navigator.mediaDevices.enumerateDevices();
  const inputs = devs.filter(d=>d.kind==='audioinput');
  selectEl.innerHTML = inputs.map((d,i)=>`<option value="${d.deviceId}">${d.label || `Mikrofon ${i+1}`}</option>`).join("") || `<option value="">(kein Mikro gefunden)</option>`;
  statusEl.textContent += inputs.length ? ` · Geräte: ${inputs.length}` : " · keine Geräte gefunden";
  return inputs.length>0;
}
async function startRecording(selectEl, statusEl, meterEl, timerEl, fileInput, label){
  try{
    const deviceId = selectEl.value || undefined;
    mic.stream = await navigator.mediaDevices.getUserMedia({ audio: deviceId ? {deviceId: {exact: deviceId}} : true });
  }catch(err){
    statusEl.textContent = `❌ Zugriff verweigert: ${err.message||err}`; return false;
  }
  mic.chunks = [];
  const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus'
             : (MediaRecorder.isTypeSupported('audio/ogg;codecs=opus') ? 'audio/ogg;codecs=opus' : '');
  mic.rec = new MediaRecorder(mic.stream, mime ? {mimeType:mime}:{});
  mic.rec.ondataavailable = e => { if (e.data && e.data.size) mic.chunks.push(e.data); };
  mic.rec.start(100);
  mic.startTs = Date.now();
  const ctx = new (window.AudioContext||window.webkitAudioContext)();
  const src = ctx.createMediaStreamSource(mic.stream);
  mic.analyser = ctx.createAnalyser();
  mic.analyser.fftSize = 512;
  src.connect(mic.analyser);
  const data = new Uint8Array(mic.analyser.frequencyBinCount);
  function tick(){
    mic.analyser.getByteTimeDomainData(data);
    let sum=0; for(let i=0;i<data.length;i++){ const v=(data[i]-128)/128; sum+=v*v; }
    const rms = Math.sqrt(sum/data.length);
    meterEl.style.width = Math.min(100, Math.max(2, Math.round(rms*140))) + "%";
    const secs = Math.floor((Date.now()-mic.startTs)/1000);
    timerEl.textContent = fmtTime(secs);
    mic.raf = requestAnimationFrame(tick);
  }
  tick();
  statusEl.textContent = `🎙️ Aufnahme läuft…`;
  fileInput.dataset.recordLabel = label || "mic_recording.webm";
  return true;
}
async function stopRecording(statusEl, meterEl, timerEl, fileInput){
  return new Promise(resolve=>{
    try{
      mic.rec.onstop = async () => {
        cancelAnimationFrame(mic.raf);
        meterEl.style.width = "0%";
        const blob = new Blob(mic.chunks, {type: mic.chunks[0]?.type || 'audio/webm'});
        const fname = fileInput.dataset.recordLabel || "mic_recording.webm";
        const file = new File([blob], fname, {type: blob.type});
        const dt = new DataTransfer();
        dt.items.add(file);
        fileInput.files = dt.files;
        mic.stream.getTracks().forEach(t=>t.stop());
        mic.stream = null; mic.rec = null; mic.chunks = [];
        statusEl.textContent = `✅ Aufnahme übernommen (${(blob.size/1024).toFixed(1)} KB)`;
        resolve(true);
      };
      mic.rec.stop();
    }catch(err){
      statusEl.textContent = `❌ Stop fehlgeschlagen: ${err.message||err}`;
      resolve(false);
    }
  });
}
export function initMicControlsTranscribe(){
  const micSelectTrans  = document.getElementById('micSelectTrans');
  const micStatusTrans  = document.getElementById('micStatusTrans');
  const micCheckTrans   = document.getElementById('micCheckTrans');
  const micStartTrans   = document.getElementById('micStartTrans');
  const micStopTrans    = document.getElementById('micStopTrans');
  const micTimerTrans   = document.getElementById('micTimerTrans');
  const micMeterTrans   = document.getElementById('micMeterTrans');
  const audioFileInput  = document.getElementById('audioFile');
  if (!micCheckTrans) return;
  micCheckTrans.addEventListener('click', ()=>checkHardware(micStatusTrans, micSelectTrans));
  micStartTrans.addEventListener('click', async ()=>{
    if (await startRecording(micSelectTrans, micStatusTrans, micMeterTrans, micTimerTrans, audioFileInput, "transcribe_mic.webm")){
      micStartTrans.disabled = true; micStopTrans.disabled = false;
    }
  });
  micStopTrans.addEventListener('click', async ()=>{
    if (await stopRecording(micStatusTrans, micMeterTrans, micTimerTrans, audioFileInput)){
      micStartTrans.disabled = false; micStopTrans.disabled = true;
    }
  });
}
export function initMicControlsEnroll(){
  const micSelect  = document.getElementById('micSelectEnroll');
  const micStatus  = document.getElementById('micStatusEnroll');
  const micCheck   = document.getElementById('micCheckEnroll');
  const micStart   = document.getElementById('micStartEnroll');
  const micStop    = document.getElementById('micStopEnroll');
  const micTimer   = document.getElementById('micTimerEnroll');
  const micMeter   = document.getElementById('micMeterEnroll');
  const audioFile  = document.getElementById('speakerFile');
  if (!micCheck) return;
  micCheck.addEventListener('click', ()=>checkHardware(micStatus, micSelect));
  micStart.addEventListener('click', async ()=>{
    if (await startRecording(micSelect, micStatus, micMeter, micTimer, audioFile, "enroll_mic.webm")){
      micStart.disabled = true; micStop.disabled = false;
    }
  });
  micStop.addEventListener('click', async ()=>{
    if (await stopRecording(micStatus, micMeter, micTimer, audioFile)){
      micStart.disabled = false; micStop.disabled = true;
    }
  });
}
