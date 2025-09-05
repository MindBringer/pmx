
import { initTabs, activeSubtab } from "./ui/tabs.js";
import { showFor } from "./utils/dom.js";
import { startSyncRun } from "./features/syncChat.js";
import { startAsyncRun, collectPersonas } from "./features/agents.js";
import { initDocsUpload } from "./features/docs.js";
import { initAudioUpload } from "./features/audio.js";
import { initSpeakers } from "./features/speakers.js";
import { renderConvStatus } from "./state/conversation.js";

initTabs();
renderConvStatus();
initDocsUpload();
initAudioUpload();
initSpeakers();

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
  toggleKeyBtn.textContent = hidden ? '🙈' : '👁️';
});

const ragChoices = document.getElementById('rag-choices');
ragChoices?.addEventListener('change', () => {
  ragChoices.querySelectorAll('.choice').forEach(c => c.classList.remove('active'));
  const sel = ragChoices.querySelector('input[name="rag"]:checked');
  sel?.parentElement?.classList.add('active');
});

const form      = document.getElementById("prompt-form");
const spinner   = document.getElementById("spinner");
const submitBtn = document.getElementById("submit-btn");
const resultDiv = document.getElementById("result");
const resultOut = document.getElementById("result-output");

form?.addEventListener("submit", async (e)=>{
  e.preventDefault();
  const prompt = document.getElementById("prompt").value.trim();
  const model  = document.getElementById("model_sys").value;
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
  if (submitBtn) submitBtn.disabled = true;

  try {
    const isAgents = activeSubtab()==='subtab-agents';
    const payload = { prompt, system, rag: ragVal };

    if (isAgents){
      const personas = collectPersonas();
      if (personas.length){
        payload.personas = personas;
        const roundsEl = document.getElementById("agent_rounds");
        const roundsVal = Number(roundsEl?.value || 1);
        if (Number.isFinite(roundsVal) && roundsVal >= 1) {
          payload.agent_rounds = Math.max(1, Math.min(10, Math.round(roundsVal)));
        }
        const criticProv = document.getElementById("critic_provider")?.value || "";
        const criticModel = (document.getElementById("critic_model")?.value || "").trim();
        if (criticProv || criticModel) payload.critic = { provider: criticProv || undefined, model: criticModel || undefined };
        if (criticProv === 'vllm') {
          payload.critic = { ...(payload.critic||{}), llm_target: 'base' };
        }
        const wProv = document.getElementById('writer_provider')?.value || '';
        const wModel = (document.getElementById('writer_model')?.value || '').trim();
        if (wProv || wModel) payload.writer = { provider: wProv || undefined, model: wModel || undefined };
        if (wProv === 'vllm') {
          payload.writer = { ...(payload.writer||{}), llm_target: 'base' };
        }
        const title = personas.map(p=>p.label||'Persona').slice(0,3).join(', ') || prompt.split('\n')[0].slice(0,80);
        hideSpinner();
        await startAsyncRun(title || 'Agentenlauf', payload);
        return;
      }
    }

    payload.model = model;
    if (!isAgents && model === 'vllm') {
      payload.llm_target = 'allrounder';  // Default für normalen Chat
    }
    await startSyncRun('Frage', payload);
  } catch (err){
    resultOut.textContent = `❌ Fehler: ${err.message}`;
    resultDiv.className = "error";
  } finally {
    hideSpinner();
    if (submitBtn) submitBtn.disabled = false;
  }
});
