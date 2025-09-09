// frontend/js/features/agents.js
import { showFor } from "../utils/dom.js";

const resultDiv = document.getElementById("result");
const resultOut = document.getElementById("result-output");
const spinner   = document.getElementById("spinner");

function renderAnswer(payload){
  const { answer, result, sources, provider, model_used, status } = payload || {};
  const txt = (answer || result || "").trim();

  // Nur Fehler anzeigen, wenn das Backend eine echte Fehlmeldung sendet
  if (!txt && status === 'error') {
    resultDiv.className = "error";
    resultOut.textContent = "❌ Fehler vom Backend (siehe Logs).";
    return;
  }
  if (!txt) {
    // Nichts rendern, wir warten noch – UI bleibt auf „läuft...“
    return;
  }

  // Erfolg
  const meta = [];
  if (provider)  meta.push(`Provider: ${provider}`);
  if (model_used) meta.push(`Model: ${model_used}`);
  const metaLine = meta.length ? `<div class="inline-help">${meta.join(" · ")}</div>` : "";
  const srcList = Array.isArray(sources) && sources.length
    ? `<details style="margin-top:8px"><summary>Quellen (${sources.length})</summary><ul>${
        sources.map(s=>`<li>${typeof s==='string'?s:JSON.stringify(s)}</li>`).join("")
      }</ul></details>`
    : "";

  resultDiv.className = "success";
  resultOut.innerHTML = `${metaLine}<div class="text">${txt.replace(/\n/g,"<br>")}</div>${srcList}`;
}

export function collectPersonas(){
  const out = [];
  for (let i = 1; i <= 5; i++) {
    const enabled  = document.getElementById(`p${i}_enabled`)?.checked;
    const label    = document.getElementById(`p${i}_label`)?.value?.trim();
    const provider = document.getElementById(`p${i}_model`)?.value || '';
    if (enabled && (label || provider)) {
      const p = { label: label || `Persona ${i}` };
      if (provider) p.provider = provider; // z.B. 'vllm', 'groq', ...
      out.push(p);
    }
  }
  return out;
}

export async function startAsyncRun(title, payload){
  const hideSpinner = showFor(spinner, 300);
  try {
    const key = (localStorage.getItem('ragApiKey') || "").trim();
    const res = await fetch("/webhook/llm", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(key ? { "x-api-key": key } : {})
      },
      body: JSON.stringify({ title: title || "Agentenlauf", async: true, ...payload })
    });

    // *** WICHTIG: ACK zuerst prüfen ***
    if (res.status === 202) {
      const ack = await res.json(); // { ok, job_id, events, result, ... }

      // leichte Statusanzeige
      resultDiv.className = "";
      resultOut.innerHTML = `
        <div class="inline-help">
          Agentenrunde gestartet – ich sammle das Ergebnis…
          ${ack.result ? `<div style="margin-top:4px"><code>${ack.result}</code></div>` : ""}
        </div>`;

      // optional: SSE für Fortschritt
      if (ack.events) {
        try {
          const es = new EventSource(ack.events);
          es.onmessage = () => {};  // du kannst hier Logs ins UI schreiben
          es.onerror = () => { try { es.close(); } catch{} };
        } catch {}
      }

      // Ergebnis pollen bis HTTP 200
      if (!ack.result) return; // ohne result-Link: nichts zu tun
      const t0 = Date.now();
      const timeoutMs = 10 * 60 * 1000;
      let wait = 1200;

      while (true) {
        const r = await fetch(ack.result, { headers: key ? { "x-api-key": key } : {} });
        if (r.status === 200) {
          const data = await r.json();   // { answer, result, sources, ... }
          renderAnswer(data);
          break;
        }
        // 202/204/404 = noch nicht fertig -> weiter warten
        if (![202,204,404].includes(r.status)) {
          const txt = await r.text().catch(()=>String(r.status));
          resultDiv.className = "error";
          resultOut.textContent = `❌ Ergebnis-Fehler (${r.status}): ${txt}`;
          break;
        }
        if (Date.now() - t0 > timeoutMs) {
          resultDiv.className = "error";
          resultOut.textContent = "⏱️ Timeout beim Warten auf Agenten-Ergebnis.";
          break;
        }
        await new Promise(s => setTimeout(s, wait));
        if (wait < 3000) wait = Math.min(3000, Math.round(wait * 1.25));
      }
      return;
    }

    // SYNC-Fall (nur wenn Agentenmodus mal nicht triggert)
    if (res.ok) {
      const data = await res.json();
      renderAnswer(data);
      return;
    }

    const errTxt = await res.text().catch(()=>String(res.status));
    resultDiv.className = "error";
    resultOut.textContent = `❌ HTTP ${res.status}: ${errTxt}`;
  } catch (e) {
    resultDiv.className = "error";
    resultOut.textContent = `❌ ${e.message}`;
  } finally {
    hideSpinner();
  }
}
