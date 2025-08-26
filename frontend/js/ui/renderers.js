import { escapeHtml } from "../utils/format.js";

const jobBox     = document.getElementById('job-status');
const jobTitleEl = document.getElementById('job-title');
const jobLine    = document.getElementById('job-statusline');
const jobLog     = document.getElementById('job-log');

export function showJob(title){
  if (!jobBox) return;
  jobTitleEl.textContent = title || 'Agentenlauf';
  jobLine.textContent  = 'Gestartet …';
  jobLog.innerHTML     = '';
  jobBox.style.display = 'block';
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
  if (evt.persona) parts.push(evt.persona);
  if (evt.role) parts.push('/'+evt.role);
  if (evt.round && evt.rounds_total) parts.push(` – Runde ${evt.round}/${evt.rounds_total}`);
  return parts.join(' ');
}

export function renderSources(sources){
  try {
    const arr = Array.isArray(sources) ? sources : [];
    if (!arr.length) return '';
    let html = `<div style="margin-top:12px;font-weight:700">Quellen</div><ul>`;
    html += arr.map((s,i)=>{
      if (typeof s === "string") return `<li>${escapeHtml(s)}</li>`;
      const title = escapeHtml(String(s.title || s.name || s.id || `Quelle ${i+1}`));
      const meta  = escapeHtml(String(s.meta || s.metadata || s.tags || ''));
      const url   = s.url ? `<a href="${escapeHtml(String(s.url))}" target="_blank" rel="noopener">Link</a>` : '';
      const snippet = escapeHtml(String(s.snippet || s.content || s.text || ''));
      return `<li><b>${title}</b>${meta?` – <span class="muted">${meta}</span>`:''} ${url}${snippet?`<div class="inline-help" style="margin-top:4px">${snippet}</div>`:''}</li>`;
    }).join('');
    html += `</ul>`;
    return html;
  } catch { return ''; }
}

/**
 * Tolerante Signatur:
 *   setFinalAnswer({ answer, sources, artifacts })
 *   setFinalAnswer("antwort-als-string", { sources, artifacts })
 */
export function setFinalAnswer(input, opts){
  const resultDiv = document.getElementById("result");
  const resultOut = document.getElementById("result-output");

  // Defensive: DOM-Container vorhanden?
  if (!resultOut || !resultDiv) {
    console.warn('setFinalAnswer: #result or #result-output nicht gefunden.');
  }

  // Eingaben normalisieren
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

  // HTML zusammenbauen
  let html = `
    <div style="display:flex;align-items:center;justify-content:space-between;gap:8px">
      <div>✅ Finale Antwort:</div>
      <button type="button" id="copy-answer" class="secondary" style="width:auto">kopieren</button>
    </div>
    <pre id="answer-pre" class="prewrap mono" style="margin-top:6px;"></pre>
  `;

  // Quellen optional anhängen
  const srcHtml = renderSources(sources);
  if (srcHtml) html += srcHtml;

  // Artifacts optional
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
        return `<li><a href="${escapeHtml(String(f.url))}" target="_blank" rel="noopener">${escapeHtml(String(f.name))}</a></li>`;
      }
      return `<li>${escapeHtml(String(f?.name || 'Datei'))}</li>`;
    }).join('') + `</ul>`;
  }

  // In DOM schreiben
  if (resultOut) resultOut.innerHTML = html;

  // Antwort-Text immer als Text (kein HTML)
  const pre = document.getElementById('answer-pre');
  if (pre) pre.textContent = safeAnswer;

  // Copy-Button
  const copyBtn = document.getElementById('copy-answer');
  if (copyBtn && pre) {
    copyBtn.addEventListener('click', ()=>{
      navigator.clipboard.writeText(pre.textContent || "");
    });
  }

  // Status setzen & Box zeigen
  if (resultDiv) {
    resultDiv.className = "success";
    resultDiv.style.display = '';
  }
  if (jobLine) jobLine.textContent = "Fertig.";
}

export function setError(msg){
  const resultDiv = document.getElementById("result");
  const resultOut = document.getElementById("result-output");
  if (resultOut) resultOut.textContent = `❌ Fehler: ${msg}`;
  if (resultDiv) {
    resultDiv.className = "error";
    resultDiv.style.display = '';
  }
}
