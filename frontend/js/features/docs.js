import { showFor } from "../utils/dom.js";
import { fmtMs, fmtBytes, escapeHtml } from "../utils/format.js";

const MEETING_WEBHOOK = "https://ai.intern/webhook/meetings/summarize";
const AUDIO_API_BASE = (typeof window !== 'undefined' && window.AUDIO_API_URL) ? window.AUDIO_API_URL : "http://localhost:6080";
const AUDIO_TRANSCRIBE_PATH = "/transcribe"; // ggf. an deine Audio-API anpassen

export function initDocsUpload(){
  // ====== Dokument-Upload → RAG ======
  const form = document.getElementById("docs-form");
  if (form){
    const uploadRes = document.getElementById("upload-result");
    const uploadOut = document.getElementById("upload-output");
    const uploadSpinner = document.getElementById("upload-spinner");
    const uploadBtn = document.getElementById("upload-btn");

    form.addEventListener("submit", async (e)=>{
      e.preventDefault();
      const apiKey = (document.getElementById("apiKey")?.value || "").trim();
      const fileEl = document.getElementById("file");
      const tagsStr = (document.getElementById("tags")?.value || "").trim();

      if (!apiKey) { if(uploadOut) uploadOut.textContent = "⚠️ Bitte API-Key eintragen."; if(uploadRes) uploadRes.className = "error"; return; }
      if (!fileEl?.files || fileEl.files.length === 0) { if(uploadOut) uploadOut.textContent = "⚠️ Bitte eine Datei auswählen."; if(uploadRes) uploadRes.className = "error"; return; }

      if (uploadOut) uploadOut.innerHTML = ""; if (uploadRes) uploadRes.className = "";
      const hideSpinner = showFor(uploadSpinner, 300);
      if (uploadBtn) uploadBtn.disabled = true;

      try {
        const fd = new FormData();
        for (const f of fileEl.files) fd.append("files", f);
        if (tagsStr) tagsStr.split(",").map(t=>t.trim()).filter(Boolean).forEach(t => fd.append("tags", t));

        const resp = await fetch("/rag/index", { method: "POST", headers: { "x-api-key": apiKey }, body: fd });
        const txt = await resp.text();
        if (!resp.ok) throw new Error(txt || `Fehler ${resp.status}`);

        let data; try { data = JSON.parse(txt); } catch { data = { raw: txt }; }
        const files = Array.isArray(data?.files) ? data.files : [];
        const tags  = data?.tags || [];
        const m     = data?.metrics || {};
        const total = typeof data?.indexed === "number" ? data.indexed : (m.total_chunks ?? files.reduce((a,b)=>a+(b.chunks||0),0));

        let html = "";
        html += `<div>✅ Index erstellt</div>`;
        html += `<div class="inline-help" style="margin-top:6px">
          Gesamt-Chunks: <b>${Number(total||0)}</b>
          ${m.elapsed_ms!=null ? ` · Laufzeit gesamt: <b>${fmtMs(m.elapsed_ms)}</b>` : ""}
          ${m.pipeline_ms!=null ? ` · Indexieren: <b>${fmtMs(m.pipeline_ms)}</b>` : ""}
          ${m.files_count!=null ? ` · Dateien: <b>${m.files_count}</b>` : ""}
        </div>`;
        if (files.length){
          html += `<ul style="margin:8px 0 0 18px">` + files.map(f=>{
            const fn = escapeHtml(String(f.filename||"unbenannt"));
            const ch = Number(f.chunks||0);
            const sz = (typeof f.size_bytes==="number") ? fmtBytes(f.size_bytes) : "–";
            const mm = escapeHtml(String(f.mime||""));
            const cv = (typeof f.conv_ms==="number") ? fmtMs(f.conv_ms) : "–";
            const cs = (typeof f.chars==="number") ? `${f.chars} Zeichen` : "";
            return `<li><b>${fn}</b> <span class="inline-help">(${mm}, ${sz})</span><br/>
                    <span class="inline-help">Chunks: <b>${ch}</b>${cs?` · ${cs}`:""} · Konvertierung+Tagging: <b>${cv}</b></span></li>`;
          }).join("") + `</ul>`;
        }
        if (tags.length) html += `<div class="inline-help" style="margin-top:8px">Tags: ${tags.map(escapeHtml).join(", ")}</div>`;

        if (!files.length && data?.raw) html += `<pre style="margin-top:6px">${escapeHtml(String(data.raw))}</pre>`;

        if (uploadOut) uploadOut.innerHTML = html;
        if (uploadRes) uploadRes.className = "success";
      } catch (err) {
        if (uploadOut) uploadOut.textContent = `❌ Fehler: ${err.message}`;
        if (uploadRes) uploadRes.className = "error";
      } finally {
        hideSpinner();
        if (uploadBtn) uploadBtn.disabled = false;
      }
    });
  }

  // ====== Audio im Reiter "Dateien" → Transcribe/Diarize/Speaker/Summary ======
  const aForm = document.getElementById("audio-form");
  if (aForm){
    const audioOutBox = document.getElementById("audio-upload-result");
    const audioOut = document.getElementById("audio-upload-output");
    const audioSpinner = document.getElementById("audio-upload-spinner");
    const audioBtn = document.getElementById("audio-upload-btn");

    aForm.addEventListener("submit", async (e)=>{
      e.preventDefault();
      if (audioOut) audioOut.innerHTML = ""; if (audioOutBox) audioOutBox.className = "upload-box";
      const hide = showFor(audioSpinner, 300);
      if (audioBtn) audioBtn.disabled = true;

      try{
        const file = document.getElementById("audioFile")?.files?.[0];
        if (!file) throw new Error("Bitte eine Audio-Datei auswählen.");
        const diar = !!document.getElementById("doDiar")?.checked;
        const ident = !!document.getElementById("doIdentify")?.checked;
        const hints = (document.getElementById("speakerHints")?.value || "").trim();
        const tags  = (document.getElementById("audioTags")?.value || "").trim();
        const summarize = !!document.getElementById("audioSummarize")?.checked;
        const model = (document.getElementById("audioModel")?.value || "vLLM");

        const fd = new FormData();
        fd.append('file', file);
        fd.append('diarize_flag', diar ? 'true' : 'false');
        fd.append('identify', ident ? 'true' : 'false');
        if (hints) fd.append('speaker_hints', hints);
        if (tags) fd.append('tags', tags);
        if (model) fd.append('model', model);

        if (summarize){
          // → Zusammenfassung via n8n Webhook
          const resp = await fetch(MEETING_WEBHOOK, { method:'POST', body: fd });
          const raw = await resp.text();
          if (!resp.ok) throw new Error(raw || `Fehler ${resp.status}`);
          let data=null; try{ data = JSON.parse(raw); }catch{}

          const summary   = data?.summary || data?.result?.summary || data?.answer || data?.text || "";
          const actions   = data?.action_items || data?.result?.action_items || data?.todos || [];
          const decisions = data?.decisions || data?.result?.decisions || [];
          const speakers  = data?.speakers || data?.result?.speakers || [];
          const sources   = data?.sources || data?.documents || [];

          let html = '';
          if (summary){
            html += '<div>✅ Fertig – Sitzungszusammenfassung</div>';
            html += '<pre class="prewrap mono" style="margin-top:6px;">' + escapeHtml(String(summary)) + '</pre>';
          } else {
            html += '<div>✅ Ergebnis empfangen.</div>';
            html += '<pre class="prewrap mono" style="margin-top:6px;">' + escapeHtml(String(raw||'')) + '</pre>';
          }
          if (actions.length){
            html += '<div style="margin-top:8px;font-weight:700">To-Dos</div><ul>' + actions.map(a=>'\n<li>' + escapeHtml(String(a?.title||a)) + '</li>').join('') + '</ul>';
          }
          if (decisions.length){
            html += '<div style="margin-top:8px;font-weight:700">Entscheidungen</div><ul>' + decisions.map(a=>'\n<li>' + escapeHtml(String(a?.title||a)) + '</li>').join('') + '</ul>';
          }
          if (speakers.length){
            html += '<div style="margin-top:8px;font-weight:700">Erkannte Sprecher</div><ul>' + speakers.map(s=>'\n<li>' + escapeHtml(String(s?.name||s)) + '</li>').join('') + '</ul>';
          }
          if (Array.isArray(sources) && sources.length){
            html += '<div style="margin-top:8px;font-weight:700">Quellen</div><ul>' + sources.map((s,i)=>{
              if (typeof s === 'string') return '<li>' + escapeHtml(s) + '</li>';
              const title = escapeHtml(String(s.title || s.name || s.id || ('Quelle ' + (i+1))));
              const url   = s.url ? (' <a href="' + escapeHtml(String(s.url)) + '" target="_blank" rel="noopener">Link</a>') : '';
              const meta  = escapeHtml(String(s.meta || s.metadata || s.tags || ''));
              return '<li><b>' + title + '</b>' + (meta?(' – <span class="muted">' + meta + '</span>'):'') + url + '</li>';
            }).join('') + '</ul>';
          }

          if (audioOut) audioOut.innerHTML = html;
          if (audioOutBox) audioOutBox.className = 'upload-box success';
        } else {
          // → direkte Transkription via Audio-API
          const url = AUDIO_API_BASE.replace(/\/$/, '') + AUDIO_TRANSCRIBE_PATH;
          const resp = await fetch(url, { method:'POST', body: fd });
          const raw  = await resp.text();
          if (!resp.ok) throw new Error(raw || `Fehler ${resp.status}`);
          let data=null; try{ data = JSON.parse(raw); }catch{}

          let html = '<div>✅ Ergebnis empfangen.</div>';
          html += '<pre class="prewrap mono" style="margin-top:6px;">' + escapeHtml(String(data ? JSON.stringify(data, null, 2) : raw)) + '</pre>';
          if (audioOut) audioOut.innerHTML = html;
          if (audioOutBox) audioOutBox.className = 'upload-box success';
        }
      } catch(err){
        if (audioOut) audioOut.textContent = '❌ Fehler: ' + err.message;
        if (audioOutBox) audioOutBox.className = 'upload-box error';
      } finally {
        hide();
        if (audioBtn) audioBtn.disabled = false;
      }
    });
  }
}
