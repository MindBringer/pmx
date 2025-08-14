# rag-backend/app/services/merge_segments.py
from typing import List, Dict

def merge_asr_diar(asr_segments: List[Dict], spk_segments: List[Dict]) -> List[Dict]:
    """
    Intersect ASR word/segment ranges with speaker segments.
    asr_segments: [{start,end,text}]
    spk_segments: [{speaker,start,end,conf,name?}]
    returns: [{speaker,name?,start,end,text}]
    """
    if not spk_segments:
        return [{"speaker":"spk1", "start": s["start"], "end": s["end"], "text": s["text"]} for s in asr_segments]

    out = []
    for a in asr_segments:
        a_mid = (a["start"] + a["end"]) / 2.0
        # choose speaker whose interval covers a_mid (fallback: closest)
        covering = [s for s in spk_segments if s["start"] <= a_mid <= s["end"]]
        if covering:
            s = max(covering, key=lambda x: x.get("conf",0.0))
        else:
            # pick nearest by center distance
            s = min(spk_segments, key=lambda x: abs(((x["start"]+x["end"])/2.0) - a_mid))
        item = {
            "speaker": s["speaker"],
            "start": a["start"],
            "end": a["end"],
            "text": a["text"]
        }
        if "name" in s:
            item["name"] = s["name"]
        out.append(item)
    return out

def to_srt(items: List[Dict]) -> str:
    def fmt(t):
        h = int(t//3600); m=int((t%3600)//60); s=t%60
        return f"{h:02d}:{m:02d}:{s:06.3f}".replace('.',',')
    lines=[]
    for i,it in enumerate(items, start=1):
        lines.append(str(i))
        lines.append(f"{fmt(it['start'])} --> {fmt(it['end'])}")
        spk = it.get("name") or it.get("speaker","spk")
        lines.append(f"[{spk}] {it['text']}")
        lines.append("")
    return "\n".join(lines)
