// /ui/js/features/syncChat.js
import { setFinalAnswer, setError } from "../ui/renderers.js";
import { getConversationId, isValidConversationId } from "../state/conversation.js";

function parseMaybeJson(text) {
  const cleaned = String(text ?? "").trim().replace(/^=\s*/, "");
  try { return JSON.parse(cleaned); } catch { return null; }
}

export async function startSyncRun(jobTitle, payload) {
  const headers = { "Content-Type": "application/json" };
  const cid = getConversationId();
  if (isValidConversationId(cid)) headers["x-conversation-id"] = cid;

  let res, bodyText;
  try {
    res = await fetch("/webhook/llm", {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });
    bodyText = await res.text();
  } catch (err) {
    setError(`Netzwerkfehler: ${err.message}`);
    throw err;
  }

  const data = parseMaybeJson(bodyText) ?? {};
  if (!res.ok) {
    const msg = data?.message || data?.error || `${res.status} ${res.statusText}`;
    setError(msg);
    throw new Error(msg);
  }

  // n8n "Format Response" → UI-Contract
  const answer =
    data?.answer ??
    data?.result ??   // <- wichtig: unser Mapper nutzt 'result'
    data?.text ??
    "";

  const sources = Array.isArray(data?.sources) ? data.sources : [];
  const artifacts = data?.artifacts || {};

  setFinalAnswer({ answer, sources, artifacts });

  return { answer, ...data }; // optional fürs Debugging
}
