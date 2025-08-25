
import { showFor } from "../utils/dom.js";
import { fmtTime, fmtMs, escapeHtml } from "../utils/format.js";
import { initMicControlsTranscribe } from "./mic.js";

export function initAudioUpload(){
  const form = document.getElementById("audio-form");
  if (!form) return;

  const audioRes     = document.getElementById("audio-upload-result");
  const audioOut     = document.getElementById("audio-upload-output");
  const audioSpinner = document.getElementById("audio-upload-spinner");
  const audioBtn     = document.getElementById("audio-upload-btn");

  form.addEventListener("submit", async (e)=>{
    e.preventDefault();
    const apiKey = document.getElementById("apiKey").value.trim();
    const fileEl = document.getElementById("audioFile");
    const tagsStr = document.getElementById("audioTags").value.trim();

    if (!apiKey) { audioOut.textContent = "⚠️ Bitte API-Key eintragen."; audioRes.className = "error"; return; }
    if (!fileEl.files || fileEl.files.length === 0) { audioOut.textContent = "⚠️ Bitte eine Audio-Datei auswählen (oder Mikrofon aufnehmen)."; audioRes.className = "error"; return; }

    audioOut.innerHTML = ""; audioRes.className = "";
    const hideSpinner = showFor(audioSpinner, 300);
    if (audioBtn) audioBtn.disabled = true;

    try {
      const fd = new FormData();
      fd.append("file", fileEl.files[0]);
      if (tagsStr) tagsStr.split(",").map(t=>t.trim()).filter(Boolean).forEach(t => fd.append("tags", t));
      const doDiar = document.getElementById("doDiar");
      const doIdentify = document.getElementById("doIdentify");
      const hints = document.getElementById("speakerHints");
      if (doDiar) fd.append("diarize_flag", doDiar.checked ? "true":"false");
      if (doIdentify) fd.append("identify", doIdentify.checked ? "true":"false");
      if (hints && hints.value.trim()) fd.append("speaker_hints", hints.value.trim());

      const resp = await fetch("/rag/transcribe", { method: "POST", headers: { "x-api-key": apiKey }, body: fd });
      const txt = await resp.text();
      if (!resp.ok) throw new Error(txt || `Fehler ${resp.status}`);

      let data; try { data = JSON.parse(txt); } catch { data = { raw: txt }; }
      const segments = Array.isArray(data?.segments) ? data.segments : null;
      const transcript = data?.text ?? data?.transcript ?? data?.transcription ?? data?.result ?? (typeof data === "string" ? data : "");
      const usedTags = data?.used_tags || data?.tags || [];
      const lang = data?.language || data?.lang;
      const dur  = data?.duration || data?.audio_duration;
      const model = data?.model || data?.whisper_model;

      let html = "";
      if (transcript) {
        html += `<div>✅ Fertig – Transkript:</div>`;
        html += `<pre class="prewrap mono" style="margin-top:6px;">${escapeHtml(String(transcript))}</pre>`;
      } else {
        html += `<div>✅ Fertig – Antwort erhalten.</div>`;
        if (data?.raw) html += `<pre style="margin-top:6px">${escapeHtml(String(data.raw))}</pre>`;
      }
      if (segments && segments.length){
        html += `<div style="margin-top:10px;font-weight:700">Segmente</div>`;
        html += `<div class="timeline">` + segments.map(s => {
          const who = s.name || s.speaker || "spk";
          const t0 = fmtTime(s.start||0), t1 = fmtTime(s.end||0);
          return `<div class="seg"><b>${escapeHtml(String(who))}</b> <span class="inline-help">[${t0}–${t1}]</span><div>${escapeHtml(String(s.text||""))}</div></div>`;
        }).join("") + `</div>`;
      }
      const metaBits = [];
      if (lang)  metaBits.push(`Sprache: ${escapeHtml(String(lang))}`);
      if (dur)   metaBits.push(`Dauer: ${escapeHtml(String(dur))}`);
      if (model) metaBits.push(`Modell: ${escapeHtml(String(model))}`);
      if (metaBits.length) html += `<div class="inline-help" style="margin-top:6px">${metaBits.join(" · ")}</div>`;
      if (Array.isArray(usedTags) && usedTags.length) html += `<div class="inline-help" style="margin-top:6px">Tags: ${usedTags.map(escapeHtml).join(", ")}</div>`;

      audioOut.innerHTML = html;
      audioRes.className = "success";
    } catch (err) {
      audioOut.textContent = `❌ Transkription fehlgeschlagen: ${err.message}`;
      audioRes.className = "error";
    } finally {
      hideSpinner();
      if (audioBtn) audioBtn.disabled = false;
    }
  });

  // Mic controls for this form
  initMicControlsTranscribe();
}
