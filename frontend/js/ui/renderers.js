// --- Live Zwischenstände (SSE) ---
// Einheitlicher Append für Zwischen-Ergebnisse
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

  // optional: Quellen/Artifacts
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

// Convenience: für Agents kann ein Event-Handler direkt aufgerufen werden
export function appendSseEvent(jobTitle, evt={}){
  const label = sseLabel(jobTitle, evt);
  const text  = (evt?.delta ?? evt?.text ?? evt?.message ?? evt?.content ?? '');
  appendIntermediate({ title: label || 'Zwischenergebnis', text, sources: evt?.sources, artifacts: evt?.artifacts });
}

// --- Finale Antwort ---
export function setFinalAnswer(input, opts){
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

  // --- Moderator-/Critic-Notizen ---
  if (artifacts?.moderator_notes) {
    const notes = String(artifacts.moderator_notes).trim();
    if (notes) {
      html += `
        <details style="margin-top:12px">
          <summary style="cursor:pointer;font-weight:700">Moderator (Critic): Fokus & Fragen</summary>
          <pre class="prewrap mono" style="margin-top:6px;">${escapeHtml(notes)}</pre>
        </details>
      `;
    }
  }

  // --- Rationale (zusammengefasst) ---
  if (artifacts?.rationale_summary) {
    const rs = artifacts.rationale_summary || {};
    const persona = Array.isArray(rs.persona) ? rs.persona : [];
    const writer  = Array.isArray(rs.writer) ? rs.writer : [];
    let rsHtml = '';

    if (persona.length) {
      rsHtml += `<div style="margin-top:8px;font-weight:600">Persona-Hinweise (zusammengefasst)</div>`;
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
      rsHtml += `<div style="margin-top:8px;font-weight:600">Writer-Hinweise (zusammengefasst)</div>`;
      rsHtml += `<ul>${writer.map(b=>`<li>${escapeHtml(String(b))}</li>`).join('')}</ul>`;
    }

    if (rsHtml) {
      html += `
        <details style="margin-top:12px">
          <summary style="cursor:pointer;font-weight:700">Rationale (zusammengefasst)</summary>
          <div class="inline-help" style="margin-top:6px">${rsHtml}</div>
        </details>
      `;
    }
  }

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
  if (resultOut) resultOut.textContent = `❌ Fehler: ${msg}`;
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

export function setMeetingResult({ summary, actions=[], decisions=[], speakers=[], sources=[], raw="" } = {}){
  if (!resultDiv || !resultOut) {
    console.warn('setMeetingResult: #result or #result-output nicht gefunden.');
    return;
  }

  let html = "";
  if (summary){
    html += `
      <div style="display:flex;align-items:center;justify-content:space-between;gap:8px">
        <div>✅ Fertig – Sitzungszusammenfassung:</div>
        <button type="button" id="copy-answer" class="secondary" style="width:auto">kopieren</button>
      </div>
      <pre id="answer-pre" class="prewrap mono" style="margin-top:6px;"></pre>
    `;
  } else {
    html += `<div>✅ Ergebnis empfangen.</div>
             <pre class="prewrap mono" style="margin-top:6px;">${escapeHtml(String(raw||""))}</pre>`;
  }

  if (Array.isArray(actions) && actions.length){
    html += `<div style="margin-top:10px;font-weight:700">To-Dos</div><ul>` +
            actions.map(a=>`<li>${escapeHtml(String(a?.title||a))}</li>`).join('') + `</ul>`;
  }
  if (Array.isArray(decisions) && decisions.length){
    html += `<div style="margin-top:10px;font-weight:700">Entscheidungen</div><ul>` +
            decisions.map(a=>`<li>${escapeHtml(String(a?.title||a))}</li>`).join('') + `</ul>`;
  }
  if (Array.isArray(speakers) && speakers.length){
    html += `<div style="margin-top:10px;font-weight:700">Erkannte Sprecher</div><ul>` +
            speakers.map(s=>`<li>${escapeHtml(String(s?.name||s))}</li>`).join('') + `</ul>`;
  }

  const srcHtml = renderSources(sources);
  if (srcHtml) html += srcHtml;

  resultOut.innerHTML = html;
  const pre = document.getElementById('answer-pre');
  if (pre) pre.textContent = asText(summary || (raw ?? ""));
  document.getElementById('copy-answer')?.addEventListener('click', ()=> navigator.clipboard.writeText(pre?.textContent||""));
  resultDiv.className = "success";
  resultDiv.style.display = '';
}

// Optional: kleine Hilfs-API für andere Module
// (z.B. features/agents.js kann diese Funktionen direkt nutzen)
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
