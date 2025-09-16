// ==============================
// File: frontend/ui/renderers.js
// Zentrale Rendering-Schicht + Live-Zwischenstände (SSE)
// Backtick-sicher (keine verschachtelten Template-Literals)
// ==============================

function esc(s){ return String(s ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }
function section(title, innerHTML, {open=false, id}={}) {
  const openAttr = open ? ' open' : '';
  const idAttr = id ? ` id="${id}"` : '';
  return `<details class="card"${openAttr}${idAttr}><summary class="card-head">${esc(title)}</summary><div class="card-body">${innerHTML}</div></details>`;
}
// Holt ersten Treffer über mehrere Quellen + mehrere Keys
function pick(sources, keys) {
  for (const src of sources) {
    if (!src || typeof src !== 'object') continue;
    for (const k of keys) {
      if (src[k] !== undefined && src[k] !== null) return src[k];
    }
  }
  return undefined;
}

// Falls utils/format.js kein asText exportiert, fallback nutzen
import { escapeHtml, asText as _asText } from "../utils/format.js";
const asText = _asText || function asTextFallback(x){
  if (x == null) return "";
  if (typeof x === "string") return x;
  try { return JSON.stringify(x, null, 2); } catch { return String(x); }
};

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
  div.textContent = "[" + new Date().toLocaleTimeString() + "] " + msg;
  jobLog.appendChild(div);
  jobLog.scrollTop = jobLog.scrollHeight;
}

export function sseLabel(jobTitle, evt){
  const parts = [];
  if (jobTitle) parts.push(jobTitle);
  if (evt && evt.persona) parts.push(evt.persona);
  if (evt && evt.role) parts.push("/" + evt.role);
  if (evt && evt.round && evt.rounds_total) parts.push(" – Runde " + evt.round + "/" + evt.rounds_total);
  return parts.join(' ');
}

export function renderSources(sources){
  try {
    const arr = Array.isArray(sources) ? sources : [];
    if (!arr.length) return '';
    let html = '<div style="margin-top:12px;font-weight:700">Quellen</div><ul>';
    html += arr.map(function(s, i){
      if (typeof s === "string") return '<li>' + escapeHtml(s) + '</li>';
      const title = escapeHtml(String(s.title || s.name || s.id || ("Quelle " + (i+1))));
      const meta  = escapeHtml(String(s.meta || s.metadata || s.tags || ''));
      const url   = s.url ? '<a href="' + escapeHtml(String(s.url)) + '" target="_blank" rel="noopener">Link</a>' : '';
      const snippet = escapeHtml(String(s.snippet || s.content || s.text || ''));
      return '<li><b>' + title + '</b>' + (meta ? ' – <span class="muted">' + meta + '</span>' : '') +
             (url ? ' ' + url : '') +
             (snippet ? '<div class="inline-help" style="margin-top:4px">' + snippet + '</div>' : '') +
             '</li>';
    }).join('');
    html += '</ul>';
    return html;
  } catch { return ''; }
}

// --- Live Zwischenstände (SSE) ---
export function appendIntermediate(payload){
  payload = payload || {};
  const tl = ensureTimeline();
  if (!tl) return;

  const title = payload.title ? String(payload.title) : '';
  const text  = asText(payload.text ?? payload.answer ?? payload.content ?? '');
  const sources = payload.sources;
  const artifacts = payload.artifacts;

  const box = document.createElement('details');
  box.open = false;
  box.className = 'intermediate-block';
  box.style.marginTop = '8px';

  const summary = document.createElement('summary');
  summary.style.cursor = 'pointer';
  summary.textContent = title || 'Zwischenergebnis';

  const pre = document.createElement('pre');
  pre.className = 'prewrap mono';
  pre.style.marginTop = '6px';
  pre.textContent = text;

  box.appendChild(summary);
  box.appendChild(pre);

  try {
    const srcHtml = renderSources(sources);
    if (srcHtml){
      const div = document.createElement('div');
      div.innerHTML = srcHtml;
      box.appendChild(div);
    }
  } catch {}

  if (artifacts && artifacts.code){
    const codeTitle = document.createElement('div');
    codeTitle.style.marginTop = '12px';
    codeTitle.style.fontWeight = '700';
    codeTitle.textContent = 'Code';
    const codePre = document.createElement('pre');
    codePre.className = 'prewrap mono';
    codePre.textContent = String(artifacts.code);
    box.appendChild(codeTitle);
    box.appendChild(codePre);
  }

  tl.appendChild(box);
}

export function appendSseEvent(jobTitle, evt){
  evt = evt || {};
  const label = sseLabel(jobTitle, evt);
  const text  = (evt.delta ?? evt.text ?? evt.message ?? evt.content ?? '');
  appendIntermediate({ title: label || 'Zwischenergebnis', text: text, sources: evt.sources, artifacts: evt.artifacts });
}

// --- Finale Antwort ---
export function setFinalAnswer(input, opts){
  if (!resultOut || !resultDiv) {
    console.warn('setFinalAnswer: #result or #result-output nicht gefunden.');
  }

  let answer = '';
  let sources;
  let artifacts;

  if (input && typeof input === 'object' && !Array.isArray(input)) {
    answer    = String(input.answer ?? input.text ?? '');
    sources   = input.sources;
    artifacts = input.artifacts;
  } else {
    answer = String(input ?? '');
  }

  if (opts && typeof opts === 'object') {
    if (sources   == null) sources   = opts.sources;
    if (artifacts == null) artifacts = opts.artifacts;
  }

  const safeAnswer = (answer || '[leer]');

  let html = ''
    + '<div style="display:flex;align-items:center;justify-content:space-between;gap:8px">'
    +   '<div>✅ Finale Antwort:</div>'
    +   '<button type="button" id="copy-answer" class="secondary" style="width:auto">kopieren</button>'
    + '</div>'
    + '<pre id="answer-pre" class="prewrap mono" style="margin-top:6px;"></pre>';

  // Moderator-/Critic-Notizen
  if (artifacts && artifacts.moderator_notes) {
    const notes = String(artifacts.moderator_notes).trim();
    if (notes) {
      html += ''
        + '<details style="margin-top:12px">'
        +   '<summary style="cursor:pointer;font-weight:700">Moderator (Critic): Fokus & Fragen</summary>'
        +   '<pre class="prewrap mono" style="margin-top:6px;">' + escapeHtml(notes) + '</pre>'
        + '</details>';
    }
  }

  // Rationale (zusammengefasst)
  if (artifacts && artifacts.rationale_summary) {
    const rs = artifacts.rationale_summary || {};
    const persona = Array.isArray(rs.persona) ? rs.persona : [];
    const writer  = Array.isArray(rs.writer) ? rs.writer : [];
    let rsHtml = '';

    if (persona.length) {
      rsHtml += '<div style="margin-top:8px;font-weight:600">Persona-Hinweise (zusammengefasst)</div>';
      rsHtml += '<ul>';
      persona.forEach(p => {
        const bullets = Array.isArray(p.bullets) ? p.bullets : [];
        const title = 'Runde ' + escapeHtml(String(p.round ?? '–')) + ' – ' + escapeHtml(String(p.label || 'Persona'));
        rsHtml += '<li><details><summary>' + title + '</summary>';
        rsHtml += '<ul>' + bullets.map(b => '<li>' + escapeHtml(String(b)) + '</li>').join('') + '</ul>';
        rsHtml += '</details></li>';
      });
      rsHtml += '</ul>';
    }

    if (writer.length) {
      rsHtml += '<div style="margin-top:8px;font-weight:600">Writer-Hinweise (zusammengefasst)</div>';
      rsHtml += '<ul>' + writer.map(b => '<li>' + escapeHtml(String(b)) + '</li>').join('') + '</ul>';
    }

    if (rsHtml) {
      html += ''
        + '<details style="margin-top:12px">'
        +   '<summary style="cursor:pointer;font-weight:700">Rationale (zusammengefasst)</summary>'
        +   '<div class="inline-help" style="margin-top:6px">' + rsHtml + '</div>'
        + '</details>';
    }
  }

  // Quellen
  const srcHtml = renderSources(sources);
  if (srcHtml) html += srcHtml;

  // Artifacts
  if (artifacts && artifacts.code) {
    html += '<div style="margin-top:12px;font-weight:700">Code</div>'
         +  '<pre class="prewrap mono">' + escapeHtml(String(artifacts.code)) + '</pre>';
  }
  if (artifacts && Array.isArray(artifacts.files) && artifacts.files.length){
    html += '<div style="margin-top:12px;font-weight:700">Dateien</div><ul>';
    html += artifacts.files.map(f=>{
      if (f && f.base64 && f.name){
        const mime = f.mime || 'application/octet-stream';
        return '<li><a download="' + escapeHtml(String(f.name)) + '" href="data:' + mime + ';base64,' + f.base64 + '">' + escapeHtml(String(f.name)) + '</a></li>';
      }
      if (f && f.url && f.name){
        return '<li><a href="' + escapeHtml(String(f.url)) + '" target="_blank" rel="noopener">' + escapeHtml(String(f.name)) + '</a></li>';
      }
      return '<li>' + escapeHtml(String((f && f.name) || 'Datei')) + '</li>';
    }).join('') + '</ul>';
  }

  if (resultOut) resultOut.innerHTML = html;

  const pre = document.getElementById('answer-pre');
  if (pre) pre.textContent = safeAnswer;

  const copyBtn = document.getElementById('copy-answer');
  if (copyBtn && pre) {
    copyBtn.addEventListener('click', ()=>{
      navigator.clipboard.writeText(pre.textContent || "");
    });
  }

  if (resultDiv) {
    resultDiv.className = "success";
    resultDiv.style.display = '';
  }
  if (jobLine) jobLine.textContent = "Fertig.";
}

export function setError(msg){
  if (resultOut) resultOut.textContent = "❌ Fehler: " + msg;
  if (resultDiv) {
    resultDiv.className = "error";
    resultDiv.style.display = '';
  }
}

export function clearResult(){
  if (resultOut) resultOut.innerHTML = '';
  if (resultDiv) {
    resultDiv.className = '';
    resultDiv.style.display = '';
  }
}

// ==============================
// ui/renderers.js – hübsches Meeting-Rendering
// ==============================

export function setMeetingResult(payload){
  payload = payload || {};
  // raw ggf. nach-JSON-parsen
  let rawObj = payload.raw;
  if (typeof rawObj === 'string') {
    try { rawObj = JSON.parse(rawObj); } catch { rawObj = null; }
  }
  const resultObj = rawObj && typeof rawObj === 'object' ? (rawObj.result || null) : null;

  // Suchreihenfolge: direktes payload → raw → raw.result
  const sources = [payload, rawObj, resultObj];

  // DEBUG
  console.debug('setMeetingResult payload=', payload);

  // Felder deutsch/englisch robust ziehen
  let summary = pick(sources, ['summary', 'tldr', 'zusammenfassung', 'answer', 'text']);
  let actions = pick(sources, ['actions', 'aktion', 'aktionen', 'todos', 'action_items']);
  let decisions = pick(sources, ['decisions', 'entscheidungen']);
  let offeneFragen = pick(sources, ['offene_fragen', 'open_questions', 'questions']);
  let risiken = pick(sources, ['risiken', 'risks']);
  let timeline = pick(sources, ['zeitachse', 'timeline']);
  let redeanteile = pick(sources, ['redeanteile', 'speaking_shares']);
  let sourcesList = pick(sources, ['sources', 'documents']);

  // Normalisieren
  const toArray = (v) => Array.isArray(v) ? v : (v==null || v==='' ? [] : [v]);
  const tldrList = Array.isArray(summary) ? summary
                   : typeof summary === 'string' ? summary.split(/\r?\n|[\u2022•-]\s*/).map(s=>s.trim()).filter(Boolean)
                   : [];

  actions = toArray(actions);
  decisions = toArray(decisions);
  offeneFragen = toArray(offeneFragen);
  risiken = toArray(risiken);
  timeline = toArray(timeline);
  redeanteile = toArray(redeanteile);
  sourcesList = toArray(sourcesList);

  // Renderer
  const renderList = (arr) => arr.length
    ? `<ul class="bullet">${arr.map(x => `<li>${esc(typeof x === 'string' ? x : x?.text ?? JSON.stringify(x))}</li>`).join('')}</ul>`
    : '<div class="inline-help">–</div>';

  const renderDecisions = (arr) => arr.length
    ? `<ul class="bullet">${arr.map(d => {
        const t = (d && typeof d === 'object') ? (d.text ?? d.title ?? d.decision ?? d) : d;
        const impact = d?.impact ? `<span class="badge" data-variant="${esc(d.impact)}">${esc(String(d.impact))}</span>` : '';
        return `<li>${esc(String(t))} ${impact}</li>`;
      }).join('')}</ul>`
    : '<div class="inline-help">–</div>';

  const renderActions = (arr) => arr.length
    ? `<div class="table">
         <div class="tr th"><div>Owner</div><div>Aufgabe</div><div>Fällig</div></div>
         ${arr.map(a => {
           const owner = a?.owner ?? a?.assignee ?? '';
           const task  = a?.task  ?? a?.title    ?? '';
           const due   = a?.due   ?? a?.due_date ?? '';
           return `<div class="tr"><div>${esc(owner)}</div><div>${esc(task)}</div><div>${esc(due)}</div></div>`;
         }).join('')}
       </div>`
    : '<div class="inline-help">–</div>';

  const renderTimeline = (arr) => arr.length
    ? `<div class="table">
         <div class="tr th"><div>von</div><div>bis</div><div>Topic</div></div>
         ${arr.map(t => `<div class="tr">
             <div>${esc(t?.from ?? t?.start ?? '')}</div>
             <div>${esc(t?.to   ?? t?.end   ?? '')}</div>
             <div>${esc(t?.topic ?? t?.title ?? '')}</div>
           </div>`).join('')}
       </div>`
    : '<div class="inline-help">–</div>';

  const renderRedeanteile = (arr) => arr.length
    ? `<div class="shares">
         ${arr.map(r => {
           const pct = Number(r?.anteil_prozent ?? r?.percent ?? 0);
           const w = Math.max(0, Math.min(100, Math.round(pct)));
           return `<div class="share-row">
             <div class="share-name">${esc(r?.name || '')}</div>
             <div class="share-bar"><i style="width:${w}%"></i></div>
             <div class="share-pct">${w}%</div>
           </div>`;
         }).join('')}
       </div>`
    : '<div class="inline-help">–</div>';

  const copyBlock = (lines) => {
    if (!lines.length) return '';
    const plain = lines.join('\n');
    const id = 'copy-' + Math.random().toString(36).slice(2);
    return `<div class="copyline"><button type="button" class="secondary" data-copy="${id}">kopieren</button></div>
      <script>(function(){ const btn=document.querySelector('button[data-copy="${id}"]'); if(!btn)return;
        btn.addEventListener('click', async()=>{ try{ await navigator.clipboard.writeText(${JSON.stringify(plain)}); btn.textContent='kopiert ✓'; setTimeout(()=>btn.textContent='kopieren',1200);}catch(e){btn.textContent='Fehler';} });
      })();</script>`;
  };

  const parts = [];
  parts.push(section('Zusammenfassung',
    tldrList.length ? `<ul class="bullet">${tldrList.map(s=>`<li>${esc(s)}</li>`).join('')}</ul>${copyBlock(tldrList)}`
                    : '<div class="inline-help">–</div>',
    {open:true, id:'sec-summary'}));

  parts.push(section('Entscheidungen', renderDecisions(decisions), {id:'sec-decisions'}));
  parts.push(section('Aktionen',      renderActions(actions),      {id:'sec-actions'}));
  parts.push(section('Offene Fragen', renderList(offeneFragen),    {id:'sec-questions'}));
  parts.push(section('Risiken',       renderList(risiken),         {id:'sec-risks'}));
  parts.push(section('Zeitachse',     renderTimeline(timeline),    {id:'sec-timeline'}));
  parts.push(section('Redeanteile',   renderRedeanteile(redeanteile), {id:'sec-shares'}));
  if (sourcesList.length) parts.push(section('Quellen', renderList(sourcesList), {id:'sec-sources'}));

  const html = `<div class="result meeting-result"><div class="done">✅ Fertig – Sitzungszusammenfassung:</div>${parts.join('')}</div>`;

  const out = document.getElementById('result-output');
  if (out) out.innerHTML = html;
  const outDocs = document.getElementById('result-output-docs');
  if (outDocs) outDocs.innerHTML = html;
}

// Optional: kleine Hilfs-API für andere Module
window.renderers = window.renderers || {
  showJob,
  updateJobStatus,
  logJob,
  sseLabel,
  appendIntermediate,
  appendSseEvent,
  setFinalAnswer,
  setMeetingResult,
  setError,
  clearResult,
  renderSources,
};
