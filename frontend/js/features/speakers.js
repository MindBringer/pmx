
import { showFor } from "../utils/dom.js";
import { escapeHtml } from "../utils/format.js";
import { initMicControlsEnroll } from "./mic.js";
export function initSpeakers(){
  const form = document.getElementById("speaker-form");
  const outBox  = document.getElementById("speaker-result");
  const out     = document.getElementById("speaker-output");
  const spinner = document.getElementById("speaker-spinner");
  const btn     = document.getElementById("speaker-enroll-btn");
  const refreshBtn = document.getElementById("speaker-refresh-btn");
  if (form){
    form.addEventListener("submit", async (e)=>{
      e.preventDefault();
      const apiKey = document.getElementById("apiKey").value.trim();
      const nameEl = document.getElementById("speakerName");
      const fileEl = document.getElementById("speakerFile");
      const name = nameEl.value.trim();
      if (!name){ out.textContent = "⚠️ Bitte Namen angeben."; outBox.className = "error upload-box"; return; }
      if (!fileEl.files || fileEl.files.length === 0){ out.textContent = "⚠️ Bitte Audio-Datei wählen (oder Mikrofon aufnehmen)."; outBox.className = "error upload-box"; return; }
      out.innerHTML = ""; outBox.className = "upload-box";
      const hideSpinner = showFor(spinner, 300);
      if (btn) btn.disabled = true;
      try{
        const fd = new FormData();
        fd.append("name", name);
        fd.append("file", fileEl.files[0]);
        const res = await fetch("/rag/speakers/enroll", { method: "POST", headers: { "x-api-key": apiKey }, body: fd });
        const txt = await res.text();
        if (!res.ok) throw new Error(txt || `HTTP ${res.status}`);
        const data = JSON.parse(txt);
        const dim = data?.dim ?? 192;
        out.innerHTML = `✅ Sprecher <b>${escapeHtml(name)}</b> hinzugefügt <span class="inline-help">(Embedding-Dim: ${dim})</span>`;
        outBox.className = "success upload-box";
        await refreshSpeakers();
        nameEl.value = ""; document.getElementById("speakerFile").value = "";
      } catch (err){
        out.textContent = `❌ Enrollment fehlgeschlagen: ${err.message}`;
        outBox.className = "error upload-box";
      } finally {
        hideSpinner();
        if (btn) btn.disabled = false;
      }
    });
  }
  if (refreshBtn) refreshBtn.addEventListener('click', refreshSpeakers);
  document.querySelectorAll('.tab[data-target="tab-docs"]').forEach(btn=>{
    btn.addEventListener('click', ()=> { refreshSpeakers(); });
  });
  initMicControlsEnroll();
}
export async function refreshSpeakers(){
  const apiKey = document.getElementById("apiKey").value.trim();
  const list = document.getElementById("speaker-list");
  if (!list) return;
  list.innerHTML = `<div class="inline-help">lädt…</div>`;
  try {
    const res = await fetch("/rag/speakers", { headers: apiKey ? { "x-api-key": apiKey } : {} });
    const txt = await res.text();
    if (!res.ok) throw new Error(txt || `HTTP ${res.status}`);
    const data = JSON.parse(txt);
    if (!Array.isArray(data) || data.length === 0){
      list.innerHTML = `<div class="inline-help">Noch keine Sprecher vorhanden.</div>`;
      return;
    }
    list.innerHTML = data.map(sp => {
      const name = (sp.name ?? "Ohne Namen");
      const id   = (sp.id ?? "");
      return `<div class="seg" style="display:flex;align-items:center;justify-content:space-between;gap:8px">
                <div>
                  <b>${escapeHtml(String(name))}</b>
                  <div class="inline-help">ID: <span class="mono">${escapeHtml(String(id))}</span></div>
                </div>
                <button type="button" data-id="${escapeHtml(String(id))}" class="secondary" style="width:auto">löschen</button>
              </div>`;
    }).join("");
    list.querySelectorAll('button[data-id]').forEach(btn=>{
      btn.addEventListener('click', async ()=>{
        const apiKey = document.getElementById("apiKey").value.trim();
        const id = btn.getAttribute('data-id');
        if (!confirm(`Sprecher wirklich löschen?\n${id}`)) return;
        const res = await fetch(`/rag/speakers/${encodeURIComponent(id)}`, { method: "DELETE", headers: apiKey ? { "x-api-key": apiKey } : {} });
        const txt = await res.text();
        if (!res.ok) { alert(`Fehler beim Löschen: ${txt||res.status}`); return; }
        await refreshSpeakers();
      });
    });
  } catch (err){
    list.innerHTML = `<div class="error">❌ Laden fehlgeschlagen: ${escapeHtml(err.message||String(err))}</div>`;
  }
}
