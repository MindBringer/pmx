
const CONV_KEY = 'conversationId';
export function isValidConversationId(id) {
  return typeof id === 'string' && id.length > 0 && id.length < 200 && !id.includes('$json') && !id.includes('{{') && /^[A-Za-z0-9._:-]+$/.test(id);
}
let conversationId = null;
try { const saved = localStorage.getItem(CONV_KEY); if (saved && isValidConversationId(saved)) conversationId = saved; } catch {}
export function getConversationId(){ return conversationId; }
export function setConversationId(id){
  if (id && isValidConversationId(id)){ conversationId = id; localStorage.setItem(CONV_KEY, id); }
  else { conversationId = null; localStorage.removeItem(CONV_KEY); }
  renderConvStatus();
}
export function renderConvStatus(){
  const el = document.getElementById('conv-status');
  if (!el) return;
  const idView = conversationId ? `<code>${conversationId}</code>` : `<i>neu</i>`;
  el.innerHTML = `Konversation: ${idView} ${conversationId ? `<button type="button" id="conv-reset" class="secondary" style="width:auto;margin-left:8px">Neue Unterhaltung</button>` : ''}`;
  document.getElementById('conv-reset')?.addEventListener('click', ()=> setConversationId(null));
}
renderConvStatus();
