
export function fmtTime(sec){const h=String(Math.floor(sec/3600)).padStart(2,"0");const m=String(Math.floor((sec%3600)/60)).padStart(2,"0");const s=String(Math.floor(sec%60)).padStart(2,"0");return `${h}:${m}:${s}`;}
export function fmtMs(ms){ if(ms==null) return "–"; if(ms<1000) return `${Math.round(ms)} ms`; return `${(ms/1000).toFixed(2)} s`; }
export function fmtBytes(b){ if(typeof b!=="number") return "–"; const u=["B","KB","MB","GB","TB"]; let i=0,n=b; while(n>=1024 && i<u.length-1){ n/=1024; i++; } return `${n.toFixed(n<10?2:(n<100?1:0))} ${u[i]}`; }
export function escapeHtml(s){ return String(s).replace(/[&<>"]/g, c=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;' }[c])); }
