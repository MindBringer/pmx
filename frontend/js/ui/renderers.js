// ==============================
// File: frontend/ui/renderers.js
// Zentrale Rendering-Schicht + Live-Zwischenstände (SSE)
// ==============================

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
  div.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
  jobLog.appendChild(div);
  jobLog.scrollTop = jobLog.scrollHeight;
}

export function sseLabel(jobTitle, evt){
  const parts = [];
  if (jobTitle) parts.push(jobTitle);
  if (evt?.persona) parts.push(evt.persona);
  if (evt?.role) parts.push('/'+evt.role);
  if (evt?.round && evt?.rounds_total) parts.push(` – Runde ${evt.round}/${evt.rounds_total}`);
  return parts.join(' ');
}

export function renderSources(sources){
  try {
    const arr = Array.isArray(sources) ? sources : [];
    if (!arr.length) return '';
    let html = `<div style=\"margin-top:12px;font-weight:700\">Quellen</div><ul>`;
    html += arr.map((s,i)=>{
      if (typeof s === "string") return `<li>${escapeHtml(s)}</li>`;
      const title = escapeHtml(String(s.title || s.name || s.id || `Quelle ${i+1}`));
      const meta  = escapeHtml(String(s.meta || s.metadata || s.tags || ''));
      const url   = s.url ? `<a href=\"${escapeHtml(String(s.url))}\" target=\"_blank\" rel=\"noopener\">Link</a>` : '';
      const snippet = escapeHtml(String(s.snippet || s.content || s.text || ''));
      return `<li><b>${title}</b>${meta?` – <span class=\"muted\">${meta}</span>`:''} ${url}${snippet?`<div class=\"inline-help\" style=\"margin-top:4px\">${snippet}</div>`:''}</li>`;
    }).join('');
    html += `</ul>`;
    return html;
  } catch { return ''; }
}

// --- Live Zwischenstände (SSE) ---
export function appendIntermediate(payload={}){
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

  if (artifacts?.code){
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

export function appendSseEvent(jobTitle, evt={}){
  const label = sseLabel(jobTitle, evt);
  const text  = (evt?.delta ?? evt?.text ?? evt?.message ?? evt?.content ?? '');
  appendIntermediate({ title: label || 'Zwischenergebnis', text, sources: evt?.sources, artifacts: evt?.artifacts });
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

  let html = `
    <div style=\"display:flex;align-items:center;justify-content:space-between;gap:8px\">
      <div>✅ Finale Antwort:</div>
      <button type=\"button\" id=\"copy-answer\" class=\"secondary\" style=\"width:auto\">kopieren</button>
    </div>
    <pre id=\"answer-pre\" class=\"prewrap mono\" style=\"margin-top:6px;\"></pre>
  `;

  if (artifacts?.moderator_notes) {
    const notes = String(artifacts.moderator_notes).trim();
    if (notes) {
      html += `
        <details style=\"margin-top:12px\">
          <summary style=\"cursor:pointer;font-weight:700\">Moderator (Critic): Fokus & Fragen</summary>
          <pre class=\"prewrap mono\" style=\"margin-top:6px;\">${escapeHtml(notes)}</pre>
        </details>
      `;
    }
  }

  if (artifacts?.rationale_summary) {
    const rs = artifacts.rationale_summary || {};
    const persona = Array.isArray(rs.persona) ? rs.persona : [];
    const writer  = Array.isArray(rs.writer) ? rs.writer : [];
    let rsHtml = '';

    if (persona.length) {
      rsHtml += `<div style=\"margin-top:8px;font-weight:600\">Persona-Hinweise (zusammengefasst)</div>`;
      rsHtml += `<ul>`;
      persona.forEach(p => {
        const bullets = Array.isArray(p.bullets) ? p.bullets : [];
        const title = `Runde ${escapeHtml(String(p.round ?? '–'))} – ${escapeHtml(String(p.label || 'Persona'))}`;
        rsHtml += `<li><details><summary>${title}</summary>`;
        rsHtml += `<ul>${bullets.map(b=>`<li>${escapeHtml(String(b))}</li>`).join('')}</ul>`;
        rsHtml += `</details></li>`;
      });
      rsHtml += `</ul>`;
    }

    if (writer.length) {
      rsHtml += `<div style=\"margin-top:8px;font-weight:600\">Writer-Hinweise (zusammengefasst)</div>`;
      rsHtml += `<ul>${writer.map(b=>`<li>${escapeHtml(String(b))}</li>`).join('')}</ul>`;
    }

    if (rsHtml) {
      html += `
        <details style=\"margin-top:12px\">
          <summary style=\"cursor:pointer;font-weight:700\">Rationale (zusammengefasst)</summary>
          <div class=\"inline-help\" style=\"margin-top:6px\">${rsHtml}</div>
        </details>
      `;
    }
  }

  const srcHtml = renderSources(sources);
  if (srcHtml) html += srcHtml;

  if (artifacts?.code) {
    html += `<div style=\"margin-top:12px;font-weight:700\">Code</div>
             <pre class=\"prewrap mono\">${escapeHtml(String(artifacts.code))}</pre>`;
  }
  if (Array.isArray(artifacts?.files) && artifacts.files.length){
    html += `<div style=\"margin-top:12px;font-weight:700\">Dateien</div><ul>`;
    html += artifacts.files.map(f=>{
      if (f?.base64 && f?.name){
        const mime = f.mime || 'application/octet-stream';
        return `<li><a download=\"${escapeHtml(String(f.name))}\" href=\"data:${mime};base64,${f.base64}\">${escapeHtml(String(f.name))}</a></li>`;
      }
      if (f?.url && f?.name){
        return `<li><a href=\"${escapeHtml(String(f.url))}\" target=\"_blank\" rel=\"noopener\">${escapeHtml(String(f.name))}</a></li>`;
      }
      return `<li>${escapeHtml(String(f?.name || 'Datei'))}</li>`;
    }).join('') + `</ul>`;
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
    resultDiv.style.display = '';}
  if (jobLine) jobLine.textContent = "Fertig.";
}

export function setError(msg){
  if (resultOut) resultOut.textContent = `❌ Fehler: ${msg}`;
  if (resultDiv) {
    resultDiv.className = "error";
    resultDiv.style.display = '';}
}

export function clearResult(){
  if (resultOut) resultOut.innerHTML = '';
  if (resultDiv) {
    resultDiv.className = '';
    resultDiv.style.display = ''; }
}

export function setMeetingResult({ summary, actions=[], decisions=[], speakers=[], sources=[], raw="" } = {}){
  if (!resultDiv || !resultOut) {
    console.warn('setMeetingResult: #result or #result-output nicht gefunden.');
    return; }

  let html = "";
  if (summary){
    html += `
      <div style=\"display:flex;align-items:center;justify-content:space-between;gap:8px\">
        <div>✅ Fertig – Sitzungszusammenfassung:</div>
        <button type=\"button\" id=\"copy-answer\" class=\"secondary\" style=\"width:auto\">kopieren</button>
      </div>
      <pre id=\"answer-pre\" class=\"prewrap mono\" style=\"margin-top:6px;\"></pre>
    `;
  } else {
    html += `<div>✅ Ergebnis empfangen.</div>
             <pre class=\"prewrap mono\" style=\"margin-top:6px;\">${escapeHtml(String(raw||\"\"))}</pre>`; }

  if (Array.isArray(actions) && actions.length){
    html += `<div style=\"margin-top:10px;font-weight:700\">To-Dos</div><ul>` +
            actions.map(a=>`<li>${escapeHtml(String(a?.title||a))}</li>`).join('') + `</ul>`; }
  if (Array.isArray(decisions) && decisions.length){
    html += `<div style=\"margin-top:10px;font-weight:700\">Entscheidungen</div><ul>` +
            decisions.map(a=>`<li>${escapeHtml(String(a?.title||a))}</li>`).join('') + `</ul>`; }
  if (Array.isArray(speakers) && speakers.length){
    html += `<div style=\"margin-top:10px;font-weight:700\">Erkannte Sprecher</div><ul>` +
            speakers.map(s=>`<li>${escapeHtml(String(s?.name||s))}</li>`).join('') + `</ul>`; }

  const srcHtml = renderSources(sources);
  if (srcHtml) html += srcHtml;

  resultOut.innerHTML = html;
  const pre = document.getElementById('answer-pre');
  if (pre) pre.textContent = asText(summary || (raw ?? \"\"));
  document.getElementById('copy-answer')?.addEventListener('click', ()=> navigator.clipboard.writeText(pre?.textContent||\"\"));
  resultDiv.className = "success";
  resultDiv.style.display = '';
}

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
