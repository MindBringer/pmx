// frontend/js/features/agents.js
import { showFor } from "../utils/dom.js";

const resultDiv = document.getElementById("result");
const resultOut = document.getElementById("result-output");
const spinner   = document.getElementById("spinner");

function renderAnswer(payload){
  const { answer, result, sources, artifacts, provider, model_used } = payload || {};
  const txt = (answer || result || "").trim();
  if (!txt) {
    resultDiv.className = "error";
    resultOut.textContent = "⚠️ Kein Text im Ergebnis.";
    return;
  }
  // simple formatting
  const meta = [];
  if (provider) meta.push(`Provider: ${provider}`);
  if (model_used) meta.push(`Model: ${model_used}`);
  const metaLine = meta.length ? `<div class="inline-help">${meta.join(" · ")}</div>` : "";
  const srcList = Array.isArray(sources) && sources.length
    ? `<details style="margin-top:8px"><summary>Quellen (${sources.length})</summary><ul>${sources.map(s=>`<li>${typeof s==='string'?s:JSON.stringify(s)}</li>`).join("")}</ul></details>`
    : "";

  resultDiv.className = "success";
  resultOut.innerHTML = `${metaLine}<div class="text">${txt.replace(/\n/g,"<br>")}</div>${srcList}`;
}

export function collectPersonas(){
  const out = [];
  for (let i = 1; i <= 5; i++) {
    const enabled  = document.getElementById(`p${i}_enabled`)?.checked;
    const label    = document.getElementById(`p${i}_label`)?.value?.trim();
    const provider = document.getElementById(`p${i}_model`)?.value || ''; // im UI "Modell", inhaltlich Provider
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
      body: JSON.stringify({
        title: title || "Agentenlauf",
        async: true,
        ...payload
      })
    });

    // 202 = ACK mit Links
    if (res.status === 202) {
      const ack = await res.json(); // { ok, job_id, events, result, started_at, ... }
      // Events (SSE) anhören – optional
      if (ack.events) {
        try {
          const es = new EventSource(ack.events);
          es.onmessage = (evt)=>{
            // Optional: Logs ins UI streamen
            // console.debug("AGENT-EVENT:", evt.data);
          };
          es.onerror = ()=>{ try { es.close(); } catch{} };
        } catch {}
      }

      // Result poll’en, bis 200 kommt
      if (!ack.result) {
        resultDiv.className="error";
        resultOut.textContent = "❌ ACK ohne result-Link.";
        return;
      }

      // sofort anzeigen, dass der Job läuft
      resultDiv.className = "";
      resultOut.innerHTML = `<div class="inline-help">Job gestartet: <code>${ack.result}</code></div>`;

      // Poll-Schleife
      const start = Date.now();
      const timeoutMs = 10 * 60 * 1000; // 10min
      // kleines Backoff
      let wait = 1200;
      while (true) {
        const r = await fetch(ack.result, { headers: key ? { "x-api-key": key } : {} });
        if (r.status === 200) {
          const data = await r.json(); // { answer, sources, artifacts, ... }
          renderAnswer(data);
          break;
        }
        if (r.status !== 202 && r.status !== 204 && r.status !== 404) {
          // Unerwartet -> Fehlermeldung anzeigen
          const txt = await r.text().catch(()=>String(r.status));
          resultDiv.className="error";
          resultOut.textContent = `❌ Ergebnis-Fehler (${r.status}): ${txt}`;
          break;
        }
        if (Date.now() - start > timeoutMs) {
          resultDiv.className="error";
          resultOut.textContent = "⏱️ Timeout beim Warten auf Agenten-Ergebnis.";
          break;
        }
        await new Promise(res => setTimeout(res, wait));
        // Backoff bis max ~3s
        if (wait < 3000) wait = Math.min(3000, Math.round(wait * 1.25));
      }
      return;
    }

    // SYNC-Fall (unerwartet im Agentenmodus, aber für Robustheit):
    if (res.ok) {
      const data = await res.json();
      renderAnswer(data);
      return;
    }

    // Fehlerfall
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
