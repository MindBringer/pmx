
import { qsa } from "../utils/dom.js";
export function initTabs(){
  qsa('.tab').forEach(btn=>{
    btn.addEventListener('click', ()=>{
      qsa('.tab').forEach(b=>b.classList.remove('active'));
      qsa('.panel').forEach(p=>p.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById(btn.dataset.target)?.classList.add('active');
    });
  });
  qsa('.subtab').forEach(btn=>{
    btn.addEventListener('click', ()=>{
      qsa('.subtab').forEach(b=>b.classList.remove('active'));
      qsa('.subpanel').forEach(p=>p.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById(btn.dataset.target)?.classList.add('active');
    });
  });
}
export function activeSubtab(){
  const a = document.querySelector('.subtab.active');
  return a ? a.dataset.target : 'subtab-sys';
}
