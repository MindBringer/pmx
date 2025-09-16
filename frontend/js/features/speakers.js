// ==============================
// File: frontend/features/speakers.js (updated)
// ==============================
import { showFor } from "../utils/dom.js";
import { escapeHtml } from "../utils/format.js";
import { initMicControlsEnroll } from "./mic.js";

// Helper: API-Key aus UI/Storage lesen, wenn globaler Helper existiert
function getApiKey() {
  try {
    if (typeof window.getRagApiKey === 'function') return window.getRagApiKey().trim();
  } catch {}
  const el = document.getElementById("apiKey");
  return (el?.value || localStorage.getItem('ragApiKey') || "").trim();
}

// Helper: robustes Fetch mit Fallback auf /speakers wenn /rag/speakers 404 liefert
async function fetchSpeakers(path, opts = {}) {
  // 1) versuche /rag/speakers*
  let res = await fetch(path, opts);
  if (res.status === 404 && path.startsWith("/rag/")) {
    // 2) fallback: gleiche Route ohne /rag
    const fallback = path.replace(/^\/rag/, "");
    res = await fetch(fallback, opts);
  }
  return res;
}

export function initSpeakers(){
  const form      = document.getElementById("speaker-form");
  const outBox    = document.getElementById("speaker-result");
  const out       = document.getElementById("speaker-output");
  const spinner   = document.getElementById("speaker-spinner");
  const btn       = document.getElementById("speaker-enroll-btn");

  // NEU: zwei Refresh-Buttons & zwei Listen
  const refreshBtnDocs      = document.getElementById("speaker-refresh-btn-docs");
  const refreshBtnSettings  = document.getElementById("speaker-refresh-btn-settings");

  if (form){
    form.addEventListener("submit", async (e)=>{
      e.preventDefault();
      const apiKey = getApiKey();
      const nameEl = document.getElementById("speakerName");
      const fileEl = document.getElementById("speakerFile");
      const name = (nameEl?.value || "").trim();

      if (!name){ if(out){out.textContent="⚠️ Bitte Namen angeben.";} if(outBox){outBox.className="error upload-box";} return; }
      if (!fileEl?.files || fileEl.files.length === 0){ if(out){out.textContent="⚠️ Bitte Audio-Datei wählen (oder Mikrofon aufnehmen).";} if(outBox){outBox.className="error upload-box";} return; }

      if (out){ out.innerHTML = ""; }
      if (outBox){ outBox.className = "upload-box"; }
      const hideSpinner = showFor(spinner, 300);
      if (btn) btn.disabled = true;

      try{
        const fd = new FormData();
        fd.append("name", name);
        fd.append("file", fileEl.files[0]);

        // bevorzugt /rag/speakers/enroll, bei 404 Fallback auf /speakers/enroll
        let res = await fetch("/rag/speakers/enroll", { method: "POST", headers: apiKey ? { "x-api-key": apiKey } : {}, body: fd });
        if (res.status === 404) {
          res = await fetch("/speakers/enroll", { method: "POST", headers: apiKey ? { "x-api-key": apiKey } : {}, body: fd });
        }
        const txt = await res.text();
        if (!res.ok) throw new Error(txt || `HTTP ${res.status}`);

        let data; try { data = JSON.parse(txt); } catch { data = {}; }
        const dim = data?.dim ?? 192;
        if (out) out.innerHTML = `✅ Sprecher <b>${escapeHtml(name)}</b> hinzugefügt <span class="inline-help">(Embedding-Dim: ${dim})</span>`;
        if (outBox) outBox.className = "success upload-box";

        // Felder zurücksetzen
        if (nameEl) nameEl.value = "";
        if (fileEl) fileEl.value = "";

        // beide Listen refreshen
        await refreshSpeakers();
      } catch (err){
        if (out) out.textContent = `❌ Enrollment fehlgeschlagen: ${err?.message || String(err)}`;
        if (outBox) outBox.className = "error upload-box";
      } finally {
        hideSpinner();
        if (btn) btn.disabled = false;
      }
    });
  }

  // Refresh-Buttons beider Tabs anschließen
  refreshBtnDocs?.addEventListener('click', refreshSpeakers);
  refreshBtnSettings?.addEventListener('click', refreshSpeakers);

  // Beim Wechsel auf den Docs-Tab ebenfalls nachladen
  document.querySelectorAll('.tab[data-target="tab-docs"]').forEach(b=>{
    b.addEventListener('click', ()=> { refreshSpeakers(); });
  });

  // Mic-Aufnahme (Enrollment) initialisieren
  initMicControlsEnroll();

  // Initialen Load machen, wenn eine der Listen vorhanden ist
  if (document.getElementById("speaker-list-docs") || document.getElementById("speaker-list-settings")) {
    refreshSpeakers();
  }
}

export async function refreshSpeakers(){
  const apiKey = getApiKey();
  const listDocs     = document.getElementById("speaker-list-docs");
  const listSettings = document.getElementById("speaker-list-settings");

  const targets = [listDocs, listSettings].filter(Boolean);
  if (targets.length === 0) return;

  const loadingHtml = `<div class="inline-help">lädt…</div>`;
  targets.forEach(t => { t.innerHTML = loadingHtml; });

  try {
    // bevorzugt /rag/speakers, Fallback /speakers
    let res = await fetchSpeakers("/rag/speakers", { headers: apiKey ? { "x-api-key": apiKey } : {} });
    const txt = await res.text();
    if (!res.ok) throw new Error(txt || `HTTP ${res.status}`);

    let data = [];
    try { data = JSON.parse(txt); } catch {}
    if (!Array.isArray(data) || data.length === 0){
      const emptyHtml = `<div class="inline-help">Noch keine Sprecher vorhanden.</div>`;
      targets.forEach(t => { t.innerHTML = emptyHtml; });
      return;
    }

    const html = data.map(sp => {
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

    targets.forEach(t => { t.innerHTML = html; });

    // Delete-Handler an beiden Listen binden
    targets.forEach(t => {
      t.querySelectorAll('button[data-id]')?.forEach(btn=>{
        btn.addEventListener('click', async ()=>{
          const id = btn.getAttribute('data-id');
          if (!id) return;
          if (!confirm(`Sprecher wirklich löschen?\n${id}`)) return;

          // bevorzugt /rag/speakers/:id, Fallback /speakers/:id
          let del = await fetch(`/rag/speakers/${encodeURIComponent(id)}`, { method: "DELETE", headers: apiKey ? { "x-api-key": apiKey } : {} });
          if (del.status === 404) {
            del = await fetch(`/speakers/${encodeURIComponent(id)}`, { method: "DELETE", headers: apiKey ? { "x-api-key": apiKey } : {} });
          }
          const txt = await del.text();
          if (!del.ok) { alert(`Fehler beim Löschen: ${txt||del.status}`); return; }
          await refreshSpeakers();
        });
      });
    });

  } catch (err){
    const errHtml = `<div class="error">❌ Laden fehlgeschlagen: ${escapeHtml(err?.message||String(err))}</div>`;
    targets.forEach(t => { t.innerHTML = errHtml; });
  }
}
