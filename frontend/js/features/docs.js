
import { showFor } from "../utils/dom.js";
import { fmtMs, fmtBytes, escapeHtml } from "../utils/format.js";

export function initDocsUpload(){
  const form = document.getElementById("docs-form");
  if (!form) return;

  const uploadRes = document.getElementById("upload-result");
  const uploadOut = document.getElementById("upload-output");
  const uploadSpinner = document.getElementById("upload-spinner");
  const uploadBtn = document.getElementById("upload-btn");

  form.addEventListener("submit", async (e)=>{
    e.preventDefault();
    const apiKey = document.getElementById("apiKey").value.trim();
    const fileEl = document.getElementById("file");
    const tagsStr = document.getElementById("tags").value.trim();

    if (!apiKey) { uploadOut.textContent = "⚠️ Bitte API-Key eintragen."; uploadRes.className = "error"; return; }
    if (!fileEl.files || fileEl.files.length === 0) { uploadOut.textContent = "⚠️ Bitte eine Datei auswählen."; uploadRes.className = "error"; return; }

    uploadOut.innerHTML = ""; uploadRes.className = "";
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

      uploadOut.innerHTML = html;
      uploadRes.className = "success";
    } catch (err) {
      uploadOut.textContent = `❌ Fehler: ${err.message}`;
      uploadRes.className = "error";
    } finally {
      hideSpinner();
      if (uploadBtn) uploadBtn.disabled = false;
    }
  });
}
