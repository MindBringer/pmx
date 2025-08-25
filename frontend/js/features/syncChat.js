
import { setConversationId, getConversationId, isValidConversationId } from "../state/conversation.js";
import { setFinalAnswer, setError } from "../ui/renderers.js";
function parseNdjsonToText(s){
  const lines = String(s).split(/\r?\n/).filter(Boolean);
  let out = "";
  for(const ln of lines){
    try{
      const obj = JSON.parse(ln);
      if (obj?.response != null) out += String(obj.response);
      else if (obj?.data?.response != null) out += String(obj.data.response);
      else if (obj?.choices?.[0]?.delta?.content != null) out += String(obj.choices[0].delta.content);
    }catch{}
  }
  return out || null;
}
function parseSseToNdjson(s){
  const events = String(s).split('\n\n');
  const dataLines = events.flatMap(ev => ev.split('\n').filter(l => l.startsWith('data:')).map(l => l.slice(5).trim()));
  return dataLines.join('\n');
}
export async function startSyncRun(job_title, payload){
  const headers = { "Content-Type": "application/json" };
  const convId = getConversationId();
  if (isValidConversationId(convId)) {
    payload.conversation_id = convId;
    headers["x-conversation-id"] = convId;
  }
  const res = await fetch("/query", { method: "POST", headers, body: JSON.stringify(payload) });
  const raw = await res.text();
  if (!res.ok){ setError(raw || `HTTP ${res.status}`); return; }
  let data = null;
  let answer = "";
  const ctype = (res.headers.get('content-type')||"").toLowerCase();
  const tryJson = () => { try{ data = JSON.parse(raw); } catch {} };
  if (ctype.includes('application/json')) {
    tryJson();
  } else if (ctype.includes('text/event-stream')) {
    const nd = parseSseToNdjson(raw);
    const txt = parseNdjsonToText(nd);
    answer = txt || nd || raw;
  } else {
    tryJson();
    if (!data) {
      const txt = parseNdjsonToText(raw);
      answer = txt || raw;
    }
  }
  if (data && typeof data === 'object') {
    answer = data?.answer ?? data?.raw_response?.response ?? data?.result ?? data?.text ?? "";
  }
  if (data?.conversation_id && isValidConversationId(data.conversation_id)){
    setConversationId(data.conversation_id);
  } else if (!convId && window.crypto?.randomUUID) {
    setConversationId(crypto.randomUUID());
  }
  const sources   = (data?.sources ?? data?.documents ?? []);
  const artifacts = (data?.artifacts ?? {});
  setFinalAnswer({ answer, sources, artifacts });
}
