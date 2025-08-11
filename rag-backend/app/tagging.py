from typing import List
from haystack_integrations.components.generators.ollama import OllamaGenerator

PROMPT = """Extrahiere prägnante Tags (1-3 Wörter, lowercase, keine Duplikate) für folgendes Dokumentfragment.
Liefere als JSON-Array reiner Strings, max 8 Tags, fokussiere auf fachliche Schlüsselbegriffe.

Text:
---
{chunk}
---
"""

def extract_tags(gen: OllamaGenerator, text: str) -> List[str]:
    resp = gen.run(prompt=PROMPT.format(chunk=text))
    out = resp.get("replies", [""])[0]
    try:
        import json, re
        arr = json.loads(re.search(r"\[.*\]", out, re.S).group(0))
        tags = [t.strip().lower().replace(" ", "-") for t in arr if isinstance(t, str)]
        return sorted(set(tags))
    except Exception:
        return []
