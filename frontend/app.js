if (!window.__APP_BIND_ONCE__) { window.__APP_BIND_ONCE__ = true; }

// Tabs
document.querySelectorAll('.tab').forEach(btn=>{
  btn.addEventListener('click',()=>{
    document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.target).classList.add('active');
  });
});

// API-Key persist + toggle
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
  toggleKeyBtn.textContent = hidden ? 'verbergen' : 'anzeigen';
});

// Radio pill styling
const ragChoices = document.getElementById('rag-choices');
ragChoices?.addEventListener('change', () => {
  ragChoices.querySelectorAll('.choice').forEach(c => c.classList.remove('active'));
  const sel = ragChoices.querySelector('input[name="rag"]:checked');
  sel?.parentElement?.classList.add('active');
});

// Helpers
function showFor(el, minMs=300){
  el.style.display = 'flex';
  const t0 = Date.now();
  return ()=>{ const dt = Date.now()-t0; const rest = Math.max(0, minMs-dt); setTimeout(()=>{ el.style.display='none'; }, rest); }
}
function fmtTime(sec){const h=String(Math.floor(sec/3600)).padStart(2,"0");const m=String(Math.floor((sec%3600)/60)).padStart(2,"0");const s=String(Math.floor(sec%60)).padStart(2,"0");return `${h}:${m}:${s}`;}
function fmtMs(ms){ if(ms==null) return "–"; if(ms<1000) return `${Math.round(ms)} ms`; return `${(ms/1000).toFixed(2)} s`; }
function fmtBytes(b){ if(typeof b!=="number") return "–"; const u=["B","KB","MB","GB","TB"]; let i=0,n=b; while(n>=1024 && i<u.length-1){ n/=1024; i++; } return `${n.toFixed(n<10?2:(n<100?1:0))} ${u[i]}`; }
function escapeHtml(str){ return String(str).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#039;"); }

// --- Streaming-/NDJSON-/SSE-Parser (robust gegen lange Antworten) ---
function parseNdjsonToText(s){
  const lines = String(s).split(/\r?\n/).filter(Boolean);
  let out = "";
  for(const ln of lines){
    try{
      const obj = JSON.parse(ln);
      if (obj?.response != null) out += String(obj.response);
      else if (obj?.data?.response != null) out += String(obj.data.response);
      else if (obj?.choices?.[0]?.delta?.content != null) out += String(obj.choices[0].delta.content);
    }catch{/* ignore */}
  }
  return out || null;
}
function parseSseToNdjson(s){
  const events = String(s).split('\n\n');
  const dataLines = events.flatMap(ev => ev.split('\n').filter(l => l.startsWith('data:')).map(l => l.slice(5).trim()));
  return dataLines.join('\n');
}

// ---------- Conversation state ----------
const CONV_KEY = 'conversationId';

function isValidConversationId(id) {
  return typeof id === 'string'
    && id.length > 0
    && id.length < 200
    && !id.includes('$json')
    && !id.includes('{{')
    && /^[A-Za-z0-9._:-]+$/.test(id);
}

let conversationId = localStorage.getItem(CONV_KEY) || null;
if (!isValidConversationId(conversationId)) {
  conversationId = null;
  localStorage.removeItem(CONV_KEY);
}

function setConversationId(id) {
  if (!isValidConversationId(id)) {
    conversationId = null;
    localStorage.removeItem(CONV_KEY);
  } else {
    conversationId = id;
    localStorage.setItem(CONV_KEY, id);
  }
  renderConvStatus();
}

function renderConvStatus(){
  const el = document.getElementById('conv-status');
  if (!el) return;
  const idView = conversationId ? `<code>${escapeHtml(conversationId)}</code>` : `<i>neu</i>`;
  el.innerHTML = `Konversation: ${idView} ${
    conversationId ? `<button type="button" id="conv-reset" class="secondary" style="width:auto;margin-left:8px">Neue Unterhaltung</button>` : ''
  }`;
  document.getElementById('conv-reset')?.addEventListener('click', ()=> setConversationId(null));
}
renderConvStatus();

// ---------- Subtabs (Anweisungen) ----------
document.querySelectorAll('.subtab').forEach(btn=>{
  btn.addEventListener('click', ()=>{
    document.querySelectorAll('.subtab').forEach(b=>b.classList.remove('active'));
    document.querySelectorAll('.subpanel').forEach(p=>p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.target).classList.add('active');
  });
});

function collectPersonas(){
  const rows = [1,2,3,4,5];
  const list = [];
  for (const i of rows){
    const en = document.getElementById(`p${i}_enabled`);
    const labEl = document.getElementById(`p${i}_label`);
    const modEl = document.getElementById(`p${i}_model`);
    if (!en || !labEl || !modEl) continue;
    const checked = !!en.checked;
    const label = (labEl.value||'').trim();
    const provider = modEl.value;
    if (checked){
      if (!label){
        throw new Error(`Bitte Jobtitel/Beschreibung für Persona ${i} eingeben.`);
      }
      list.push({ label, provider });
    }
  }
  return list;
}

function activeSubtab(){
  const a = document.querySelector('.subtab.active');
  return a ? a.dataset.target : 'subtab-sys';
}

// ---------- Prompt senden ----------
const form = document.getElementById("prompt-form");
const resultDiv = document.getElementById("result");
const resultOut = document.getElementById("result-output");
const spinner = document.getElementById("spinner");
const submitBtn = document.getElementById("submit-btn");

function renderSources(sources){
  if (!Array.isArray(sources) || sources.length === 0) return "";
  const items = sources.map((s, i) => {
    if (typeof s === "string") return `<li>${escapeHtml(s)}</li>`;
    if (s && typeof s === "object") {
      const title = s.title || s.name || s.meta?.title || s.file_name || `Quelle ${i+1}`;
      const origin = s.source || s.meta?.source || "";
      const score  = (s.score != null) ? ` · Score: <b>${Number(s.score).toFixed(3)}</b>` : "";
      const tags   = Array.isArray(s.tags) && s.tags.length ? ` · Tags: ${s.tags.map(escapeHtml).join(", ")}` : "";
      const href   = s.url || s.link;
      const head   = href ? `<a href="${href}" target="_blank" rel="noopener">${escapeHtml(String(title))}</a>` : escapeHtml(String(title));
      const snippet = s.snippet || s.content || s.text || "";
      return `<li><b>${head}</b>${origin?` <span class="inline-help">(${escapeHtml(String(origin))})</span>`:""}${score}${tags}${snippet?`<div class="inline-help" style="margin-top:4px">${escapeHtml(String(snippet))}</div>`:""}</li>`;
    }
    return `<li>${escapeHtml(String(s))}</li>`;
  }).join("");
  return `<div class="inline-help" style="margin-top:8px">Quellen:</div><ul class="sources">${items}</ul>`;
}

// === Async Job (SSE) UI helpers ===
const jobBox   = document.getElementById('job-status');
const jobTitleEl = document.getElementById('job-title');
const jobLine  = document.getElementById('job-statusline');
const jobLog   = document.getElementById('job-log');

function showJob(title){
  if (!jobBox) return;
  jobTitleEl.textContent = title || 'Agentenlauf';
  jobLine.textContent  = 'Gestartet …';
  jobLog.innerHTML     = '';
  jobBox.style.display = 'block';
}
function logJob(msg){
  if (!jobLog) return;
  const div = document.createElement('div');
  div.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
  jobLog.appendChild(div);
  jobLog.scrollTop = jobLog.scrollHeight;
}
function sseLabel(jobTitle, evt){
  const parts = [];
  if (jobTitle) parts.push(jobTitle);
  if (evt.persona) parts.push(evt.persona);
  if (evt.role) parts.push('/'+evt.role);
  if (evt.round && evt.rounds_total) parts.push(` – Runde ${evt.round}/${evt.rounds_total}`);
  return parts.join(' ');
}

async function startAsyncRun(job_title, payload){
  const headers = { "Content-Type": "application/json" };
  if (isValidConversationId(conversationId)) {
    payload.conversation_id = conversationId;
    headers["x-conversation-id"] = conversationId;
  }
  payload.async = true;
  payload.title = job_title;

  const res = await fetch("/webhook/llm", { method: "POST", headers, body: JSON.stringify(payload) });
  const ackText = await res.text();
  let ack = {};
  try { ack = JSON.parse(ackText.trim().replace(/^=\s*/, "")); } catch {}
  console.debug("[ACK]", res.status, ackText);

  const jobId =
    ack.job_id ||
    (typeof ack.events === "string" && ack.events.match(/\/rag\/jobs\/([^/]+)/)?.[1]) ||
    (typeof ack.result === "string" && ack.result.match(/\/rag\/jobs\/([^/]+)/)?.[1]) || "";

  if (!res.ok || !jobId) throw new Error(ack?.message || ack?.error || `Start fehlgeschlagen (${res.status})`);
  ack.job_id = jobId;

  showJob(job_title || payload?.prompt || "Agentenlauf");

  const looksOk = (u) => {
    if (typeof u !== "string" || !u) return false;
    if (u.includes("{{") || u.includes("$json")) return false;
    try {
      const url = new URL(u, location.href);
      return url.origin === location.origin && url.pathname.startsWith("/rag/jobs/");
    } catch { return false; }
  };

  const eventsUrl = looksOk(ack.events) ? ack.events : `/rag/jobs/${encodeURIComponent(jobId)}/events`;

  try { window.__es?.close(); } catch {}
  const src = new EventSource(eventsUrl, { withCredentials: true });
  window.__es = src;

  logJob(`Verbinde: ${eventsUrl}`);
  src.onopen  = () => logJob("SSE verbunden.");
  src.onerror = () => logJob("Stream-Fehler (SSE) – versuche verbunden zu bleiben …");
  src.onmessage = (e) => {
    try {
      const evt = JSON.parse(e.data);
      jobLine.textContent = sseLabel(job_title, evt);
      if (evt.message) logJob(evt.message);
    } catch {
      logJob(String(e.data || 'Event ohne JSON'));
    }
  };

  const resultUrl = looksOk(ack.result) ? ack.result : `/rag/jobs/${encodeURIComponent(jobId)}/result`;
  const final = await fetch(resultUrl).then(r=>r.json());
  if (final?.status === "done"){
    const answer = final.result?.answer || "";
    const artifacts = final.result?.artifacts || {};
    const sources   = final.result?.sources || final.result?.documents || [];

    let html = `
      <div style="display:flex;align-items:center;justify-content:space-between;gap:8px">
        <div>✅ Finale Antwort:</div>
        <button type="button" id="copy-answer" class="secondary" style="width:auto">kopieren</button>
      </div>
      <pre id="answer-pre" class="prewrap mono" style="margin-top:6px;"></pre>
    `;
    html += renderSources(sources);

    if (artifacts?.code) {
      html += `<div style="margin-top:12px;font-weight:700">Code</div>
               <pre class="prewrap mono">${escapeHtml(String(artifacts.code))}</pre>`;
    }
    if (Array.isArray(artifacts?.files) && artifacts.files.length){
      html += `<div style="margin-top:12px;font-weight:700">Dateien</div><ul>`;
      html += artifacts.files.map(f=>{
        if (f?.base64 && f?.name){
          const mime = f.mime || 'application/octet-stream';
          return `<li><a download="${escapeHtml(String(f.name))}" href="data:${mime};base64,${f.base64}">${escapeHtml(String(f.name))}</a></li>`;
        }
        if (f?.url && f?.name){
          return `<li><a href="${escapeHtml(String(f.name))}" target="_blank" rel="noopener">${escapeHtml(String(f.name))}</a></li>`;
        }
        return `<li>${escapeHtml(String(f?.name || 'Datei'))}</li>`;
      }).join('') + `</ul>`;
    }

    resultOut.innerHTML = html;
    const pre = document.getElementById('answer-pre');
    pre.textContent = String(answer || "[leer]");
    document.getElementById('copy-answer')?.addEventListener('click', ()=>{
      navigator.clipboard.writeText(pre.textContent||"");
    });
    resultDiv.className = "success";
    if (jobLine) jobLine.textContent = "Fertig.";
  } else {
    if (jobLine) jobLine.textContent = "Noch in Arbeit …";
  }
}

form?.addEventListener("submit", async function (e) {
  e.preventDefault();
  const prompt = document.getElementById("prompt").value.trim();
  const model = document.getElementById("model_sys").value;
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
  submitBtn.disabled = true;

  try {
    const isAgents = activeSubtab()==='subtab-agents';
    const personas = isAgents ? collectPersonas() : [];

    const payload = { prompt, system, rag: ragVal };
    if (isAgents) {
      const roundsEl = document.getElementById("agent_rounds");
      const roundsVal = Number(roundsEl?.value || 1);
      if (Number.isFinite(roundsVal) && roundsVal >= 1) {
        payload.agent_rounds = Math.max(1, Math.min(10, Math.round(roundsVal)));
      }
      const criticProv = document.getElementById("critic_provider")?.value || "";
      const criticModel = (document.getElementById("critic_model")?.value || "").trim();
      if (criticProv || criticModel) {
        payload.critic = {};
        if (criticProv) payload.critic.provider = criticProv;
        if (criticModel) payload.critic.model = criticModel;
      }
    }

    if (personas.length > 0){
      payload.personas = personas;
      const wProv = document.getElementById('writer_provider')?.value || '';
      const wModel = (document.getElementById('writer_model')?.value || '').trim();
      if (wProv || wModel) {
        payload.writer = {};
        if (wProv) payload.writer.provider = wProv;
        if (wModel) payload.writer.model = wModel;
      }
    } else {
      payload.model = model;
    }

    if (isAgents && personas.length>0){
      const titleFromPrompt = prompt.split('\n')[0].slice(0, 80);
      const titleFromPersonas = personas.map(p=>p.label).slice(0,3).join(', ');
      const jobTitle = titleFromPersonas || titleFromPrompt || 'Agentenlauf';
      hideSpinner();
      await startAsyncRun(jobTitle, payload);
      return;
    }

    const headers = { "Content-Type": "application/json" };
    if (isValidConversationId(conversationId)) {
      payload.conversation_id = conversationId;
      headers["x-conversation-id"] = conversationId;
    }

    const response = await fetch("/webhook/llm", { method: "POST", headers, body: JSON.stringify(payload) });
    const rawText = await response.text();
    if (!response.ok) throw new Error(rawText || `HTTP ${response.status}`);

    let data = null;
    let answer = "";
    const ctype = (response.headers.get('content-type')||"").toLowerCase();
    const tryJsonFirst = ()=>{ try{ data = JSON.parse(rawText); }catch{} };
    if (ctype.includes('application/json')) {
      tryJsonFirst();
    } else if (ctype.includes('text/event-stream')) {
      const nd = parseSseToNdjson(rawText);
      const txt = parseNdjsonToText(nd);
      answer = txt || nd || rawText;
    } else {
      tryJsonFirst();
      if (!data) {
        const txt = parseNdjsonToText(rawText);
        answer = txt || rawText;
      }
    }

    if (data && typeof data === 'object') {
      answer = data?.answer ?? data?.raw_response?.response ?? data?.result ?? data?.text ?? "";
    }

    if (data?.conversation_id && isValidConversationId(data.conversation_id)) {
      setConversationId(data.conversation_id);
    } else if (!conversationId && window.crypto?.randomUUID) {
      setConversationId(crypto.randomUUID());
    }

    const sources   = (data?.sources ?? data?.documents ?? []);
    const artifacts = (data?.artifacts ?? {});

    let html = `
      <div style="display:flex;align-items:center;justify-content:space-between;gap:8px">
        <div>✅ Fertig – Antwort:</div>
        <button type="button" id="copy-answer" class="secondary" style="width:auto">kopieren</button>
      </div>
      <pre id="answer-pre" class="prewrap mono" style="margin-top:6px;"></pre>
    `;

    html += renderSources(sources);

    if (artifacts?.code) {
      html += `<div style="margin-top:12px;font-weight:700">Code</div>
               <pre class="prewrap mono">${escapeHtml(String(artifacts.code))}</pre>`;
    }
    if (Array.isArray(artifacts?.files) && artifacts.files.length){
      html += `<div style="margin-top:12px;font-weight:700">Dateien</div><ul>`;
      html += artifacts.files.map(f=>{
        if (f?.base64 && f?.name){
          const mime = f.mime || 'application/octet-stream';
          return `<li><a download="${escapeHtml(String(f.name))}" href="data:${mime};base64,${f.base64}">${escapeHtml(String(f.name))}</a></li>`;
        }
        if (f?.url && f?.name){
          return `<li><a href="${escapeHtml(String(f.name))}" target="_blank" rel="noopener">${escapeHtml(String(f.name))}</a></li>`;
        }
        return `<li>${escapeHtml(String(f?.name || 'Datei'))}</li>`;
      }).join('') + `</ul>`;
    }

    resultOut.innerHTML = html;
    const pre = document.getElementById('answer-pre');
    pre.textContent = String(answer || (data && !answer ? JSON.stringify(data, null, 2) : rawText));
    document.getElementById('copy-answer')?.addEventListener('click', ()=>{
      navigator.clipboard.writeText(pre.textContent||"");
    });
    resultDiv.className = "success";
  } catch (err) {
    resultOut.textContent = `❌ Fehler: ${err.message}`;
    resultDiv.className = "error";
  } finally {
    hideSpinner();
    submitBtn.disabled = false;
  }
});

// ---------- Dokumente indexieren ----------
const docsForm = document.getElementById("docs-form");
const uploadRes = document.getElementById("upload-result");
const uploadOut = document.getElementById("upload-output");
const uploadSpinner = document.getElementById("upload-spinner");
const uploadBtn = document.getElementById("upload-btn");

docsForm?.addEventListener("submit", async function (e) {
  e.preventDefault();
  const apiKey = document.getElementById("apiKey").value.trim();
  const fileEl = document.getElementById("file");
  const tagsStr = document.getElementById("tags").value.trim();

  if (!apiKey) { uploadOut.textContent = "⚠️ Bitte API-Key eintragen."; uploadRes.className = "error"; return; }
  if (!fileEl.files || fileEl.files.length === 0) { uploadOut.textContent = "⚠️ Bitte eine Datei auswählen."; uploadRes.className = "error"; return; }

  uploadOut.innerHTML = ""; uploadRes.className = "";
  const hideSpinner = showFor(uploadSpinner, 300);
  uploadBtn.disabled = true;

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
    uploadBtn.disabled = false;
  }
});

// ---------- Sprecher Enrollment ----------
const speakerForm    = document.getElementById("speaker-form");
const speakerOutBox  = document.getElementById("speaker-result");
const speakerOut     = document.getElementById("speaker-output");
const speakerSpinner = document.getElementById("speaker-spinner");
const speakerBtn     = document.getElementById("speaker-enroll-btn");
const speakerRefresh = document.getElementById("speaker-refresh-btn");

if (speakerForm) {
  speakerForm.addEventListener("submit", async function(e){
    e.preventDefault();
    const apiKey = document.getElementById("apiKey").value.trim();
    const nameEl = document.getElementById("speakerName");
    const fileEl = document.getElementById("speakerFile");
    const name = nameEl.value.trim();

    if (!name){ speakerOut.textContent = "⚠️ Bitte Namen angeben."; speakerOutBox.className = "error upload-box"; return; }
    if (!fileEl.files || fileEl.files.length === 0){ speakerOut.textContent = "⚠️ Bitte Audio-Datei wählen (oder Mikrofon aufnehmen)."; speakerOutBox.className = "error upload-box"; return; }

    speakerOut.innerHTML = "";
    speakerOutBox.className = "upload-box";
    const hideSpinner = showFor(speakerSpinner, 300);
    speakerBtn.disabled = true;

    try{
      const fd = new FormData();
      fd.append("name", name);
      fd.append("file", fileEl.files[0]);

      const res = await fetch("/rag/speakers/enroll", { method: "POST", headers: { "x-api-key": apiKey }, body: fd });
      const txt = await res.text();
      if (!res.ok) throw new Error(txt || `HTTP ${res.status}`);
      const data = JSON.parse(txt);

      const dim = data?.dim ?? 192;
      speakerOut.innerHTML = `✅ Sprecher <b>${escapeHtml(name)}</b> hinzugefügt <span class="inline-help">(Embedding-Dim: ${dim})</span>`;
      speakerOutBox.className = "success upload-box";
      await refreshSpeakers();
      nameEl.value = ""; document.getElementById("speakerFile").value = "";
    } catch (err){
      speakerOut.textContent = `❌ Enrollment fehlgeschlagen: ${err.message}`;
      speakerOutBox.className = "error upload-box";
    } finally {
      hideSpinner();
      speakerBtn.disabled = false;
    }
  });

  speakerRefresh?.addEventListener('click', refreshSpeakers);
  document.querySelectorAll('.tab[data-target="tab-docs"]').forEach(btn=>{
    btn.addEventListener('click', ()=> { refreshSpeakers(); });
  });
}

async function refreshSpeakers(){
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
        const res = await fetch(`/rag/speakers/${encodeURIComponent(id)}`, {
          method: "DELETE", headers: apiKey ? { "x-api-key": apiKey } : {}
        });
        const txt = await res.text();
        if (!res.ok) { alert(`Fehler beim Löschen: ${txt||res.status}`); return; }
        await refreshSpeakers();
      });
    });
  } catch (err){
    list.innerHTML = `<div class="error">❌ Laden fehlgeschlagen: ${escapeHtml(err.message||String(err))}</div>`;
  }
}

// ---------- Microphone: shared engine ----------
const mic = { stream: null, rec: null, chunks: [], analyser: null, raf: 0, startTs: 0, target: null };
function isSecure(){ return location.protocol === 'https:' || location.hostname === 'localhost' || location.hostname === '127.0.0.1'; }

async function checkHardware(statusEl, selectEl){
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia){
    if (statusEl) statusEl.textContent = "❌ Kein getUserMedia verfügbar (Browser zu alt?).";
    return false;
  }
  if (!isSecure()){
    if (statusEl) statusEl.textContent = "❌ Unsichere Seite. Mikrofon benötigt HTTPS oder localhost.";
    return false;
  }
  try{
    if (navigator.permissions && navigator.permissions.query){
      const p = await navigator.permissions.query({name:'microphone'});
      if (statusEl) statusEl.textContent = `Berechtigung: ${p.state}`;
    } else {
      if (statusEl) statusEl.textContent = "Berechtigung: unbekannt";
    }
  }catch{}

  await navigator.mediaDevices.getUserMedia({audio:true}).then(s=>s.getTracks().forEach(t=>t.stop())).catch(()=>{});
  const devs = await navigator.mediaDevices.enumerateDevices();
  const inputs = devs.filter(d=>d.kind==='audioinput');
  if (selectEl) selectEl.innerHTML = inputs.map((d,i)=>`<option value="${d.deviceId}">${d.label || `Mikrofon ${i+1}`}</option>`).join("") || `<option value="">(kein Mikro gefunden)</option>`;
  if (statusEl) statusEl.textContent += inputs.length ? ` · Geräte: ${inputs.length}` : " · keine Geräte gefunden";
  return inputs.length>0;
}

async function startRecording(selectEl, statusEl, meterEl, timerEl, fileInput, label){
  try{
    const deviceId = selectEl?.value || undefined;
    mic.stream = await navigator.mediaDevices.getUserMedia({ audio: deviceId ? {deviceId: {exact: deviceId}} : true });
  }catch(err){
    if (statusEl) statusEl.textContent = `❌ Zugriff verweigert: ${err.message||err}`;
    return false;
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
    if (meterEl) meterEl.style.width = Math.min(100, Math.max(2, Math.round(rms*140))) + "%";
    const secs = Math.floor((Date.now()-mic.startTs)/1000);
    if (timerEl) timerEl.textContent = fmtTime(secs);
    mic.raf = requestAnimationFrame(tick);
  }
  tick();

  if (statusEl) statusEl.textContent = `🎙️ Aufnahme läuft…`;
  if (fileInput) fileInput.dataset.recordLabel = label || "mic_recording.webm";
  return true;
}

async function stopRecording(statusEl, meterEl, timerEl, fileInput){
  return new Promise(resolve=>{
    try{
      mic.rec.onstop = async () => {
        cancelAnimationFrame(mic.raf);
        if (meterEl) meterEl.style.width = "0%";
        const blob = new Blob(mic.chunks, {type: mic.chunks[0]?.type || 'audio/webm'});
        const fname = (fileInput && fileInput.dataset.recordLabel) || "mic_recording.webm";
        const file = new File([blob], fname, {type: blob.type});
        const dt = new DataTransfer();
        dt.items.add(file);
        if (fileInput) fileInput.files = dt.files;

        mic.stream.getTracks().forEach(t=>t.stop());
        mic.stream = null; mic.rec = null; mic.chunks = [];

        if (statusEl) statusEl.textContent = `✅ Aufnahme übernommen (${(blob.size/1024).toFixed(1)} KB)`;
        resolve(true);
      };
      mic.rec.stop();
    }catch(err){
      if (statusEl) statusEl.textContent = `❌ Stop fehlgeschlagen: ${err.message||err}`;
      resolve(false);
    }
  });
}

// Wire up Transcribe mic controls
const micSelectTrans  = document.getElementById('micSelectTrans');
const micStatusTrans  = document.getElementById('micStatusTrans');
const micCheckTrans   = document.getElementById('micCheckTrans');
const micStartTrans   = document.getElementById('micStartTrans');
const micStopTrans    = document.getElementById('micStopTrans');
const micTimerTrans   = document.getElementById('micTimerTrans');
const micMeterTrans   = document.getElementById('micMeterTrans');
const audioFileInput  = document.getElementById('audioFile');

micCheckTrans?.addEventListener('click', ()=>checkHardware(micStatusTrans, micSelectTrans));
micStartTrans?.addEventListener('click', async ()=>{
  if (await startRecording(micSelectTrans, micStatusTrans, micMeterTrans, micTimerTrans, audioFileInput, "transcribe_mic.webm")){
    micStartTrans.disabled = true; micStopTrans.disabled = false;
  }
});
micStopTrans?.addEventListener('click', async ()=>{
  if (await stopRecording(micStatusTrans, micMeterTrans, micTimerTrans, audioFileInput)){
    micStartTrans.disabled = false; micStopTrans.disabled = true;
  }
});

// Wire up Enroll mic controls
const micSelectEnroll = document.getElementById('micSelectEnroll');
const micStatusEnroll = document.getElementById('micStatusEnroll');
const micCheckEnroll  = document.getElementById('micCheckEnroll');
const micStartEnroll  = document.getElementById('micStartEnroll');
const micStopEnroll   = document.getElementById('micStopEnroll');
const micTimerEnroll  = document.getElementById('micTimerEnroll');
const speakerFileInput= document.getElementById('speakerFile');

micCheckEnroll?.addEventListener('click', ()=>checkHardware(micStatusEnroll, micSelectEnroll));
micStartEnroll?.addEventListener('click', async ()=>{
  if (await startRecording(micSelectEnroll, micStatusEnroll, micMeterEnroll, micTimerEnroll, speakerFileInput, "speaker_enroll_mic.webm")){
    micStartEnroll.disabled = true; micStopEnroll.disabled = false;
  }
});
micStopEnroll?.addEventListener('click', async ()=>{
  if (await stopRecording(micStatusEnroll, micMeterEnroll, micTimerEnroll, speakerFileInput)){
    micStartEnroll.disabled = false; micStopEnroll.disabled = true;
  }
});

// Optional: beim Öffnen des Tabs einmal Hardware grob prüfen
document.querySelectorAll('.tab[data-target="tab-docs"]').forEach(btn=>{
  btn.addEventListener('click', async ()=>{
    await checkHardware(micStatusTrans, micSelectTrans);
    await checkHardware(micStatusEnroll, micSelectEnroll);
  });
});

// =====================================================
// Unified Audio + Meeting – EIN Upload, EIN Flow (/summarize)
// =====================================================

// Persist/lesen der Webhook-URL (falls Feld existiert; Default /summarize)
const meetingWebhookEl = document.getElementById("meetingWebhook");
try {
  const saved = localStorage.getItem('meetingWebhookUrl');
  if (saved && meetingWebhookEl) meetingWebhookEl.value = saved;
  meetingWebhookEl?.addEventListener('input', ()=>{
    localStorage.setItem('meetingWebhookUrl', meetingWebhookEl.value.trim());
  });
} catch {}

function getMeetingWebhook(){
  const v = (meetingWebhookEl?.value || "").trim();
  return v || "/summarize";
}

// Einmalige Bindungen
function bindOnce(el, evt, fn){
  if (!el) return;
  const key = `__bound_${evt}`;
  if (el.dataset[key] === "1") return;
  el.dataset[key] = "1";
  el.addEventListener(evt, fn);
}

// Gemeinsamer Submit-Handler für Audio- und Meeting-Form
async function handleAudioMeetingSubmit(e){
  e.preventDefault();

  const apiKey = document.getElementById("apiKey")?.value?.trim();
  const hideSpinner = showFor(spinner, 300);
  resultOut.innerHTML = "";
  resultDiv.className = "";

  try {
    // Dateiquelle: bevorzugt #audioFile, sonst #meetingFile
    const audioFileEl   = document.getElementById("audioFile");
    const meetingFileEl = document.getElementById("meetingFile");
    const file = audioFileEl?.files?.[0] || meetingFileEl?.files?.[0];
    if (!file) throw new Error("Bitte eine Audio-Datei auswählen (oder Mikrofon aufnehmen).");

    // Flags: Audio-IDs und Meeting-IDs unterstützen
    const diarCk  = document.getElementById("doDiar")     || document.getElementById("meetDiarize");
    const identCk = document.getElementById("doIdentify") || document.getElementById("meetIdentify");
    const hintsEl = document.getElementById("speakerHints") || document.getElementById("meetSpeakerHints");
    const tagsStr = (document.getElementById("audioTags")?.value || "").trim();

    const fd = new FormData();
    fd.append("file", file);
    if (tagsStr) tagsStr.split(",").map(t=>t.trim()).filter(Boolean).forEach(t => fd.append("tags", t));
    if (diarCk)  fd.append("diarize_flag", diarCk.checked ? "true" : "false");
    if (identCk) fd.append("identify",     identCk.checked ? "true" : "false");
    if (hintsEl && hintsEl.value.trim()) fd.append("speaker_hints", hintsEl.value.trim());

    const headers = {};
    if (apiKey) headers["x-api-key"] = apiKey;

    const hook = getMeetingWebhook();
    const resp = await fetch(hook, { method: "POST", headers, body: fd });
    const txt  = await resp.text();
    if (!resp.ok) throw new Error(txt || `Fehler ${resp.status}`);

    let data; try { data = JSON.parse(txt); } catch { data = { raw: txt }; }

    // Falls Backend Flags nicht liefert, lokal ergänzen:
    data.flags = Object.assign({}, data.flags || {}, {
      diarize:  !!(diarCk && diarCk.checked),
      identify: !!(identCk && identCk.checked),
      summary:  !!(document.getElementById("summary")?.checked) // optionales UI-Flag
    });

    // Einheitliches Rendering (Meeting+Audio zusammengeführt)
    if (window.renderers?.setAudioMeetingResult) {
      window.renderers.setAudioMeetingResult(data);
    } else if (window.renderers?.setMeetingResult) {
      window.renderers.setMeetingResult(data);
    } else {
      // letzter Fallback
      const ans = data?.answer || data?.text || data?.transcript || txt;
      resultOut.innerHTML = `<pre class="prewrap mono">${escapeHtml(String(ans))}</pre>`;
      resultDiv.className = "success";
    }
  } catch (err){
    resultOut.textContent = `❌ Fehler: ${err.message}`;
    resultDiv.className = "error";
  } finally {
    hideSpinner();
  }
}

// Beide Formulare (falls vorhanden) auf den EINEN Handler legen
bindOnce(document.getElementById("audio-form"),   "submit", handleAudioMeetingSubmit);
bindOnce(document.getElementById("meeting-form"), "submit", handleAudioMeetingSubmit);
