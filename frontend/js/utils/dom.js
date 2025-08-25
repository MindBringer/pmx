
export const qs  = (sel, el=document) => el.querySelector(sel);
export const qsa = (sel, el=document) => Array.from(el.querySelectorAll(sel));
export function on(el, ev, fn, opts) { el.addEventListener(ev, fn, opts); return () => el.removeEventListener(ev, fn, opts); }
export function showFor(el, minMs=300){
  el.style.display = 'flex';
  const t0 = Date.now();
  return ()=>{ const dt = Date.now()-t0; const rest = Math.max(0, minMs-dt); setTimeout(()=>{ el.style.display='none'; }, rest); }
}
