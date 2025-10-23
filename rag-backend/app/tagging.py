# app/tagging.py
"""
Auto-Tagging für Dokumente mittels LLM
"""
import re
from typing import List


def extract_tags(generator, content: str, max_tags: int = 8) -> List[str]:
    """
    Extrahiert relevante Tags aus Dokumenten-Content mittels LLM
    
    Args:
        generator: Haystack Generator (z.B. OpenAIGenerator für vLLM)
        content: Text-Content des Dokuments
        max_tags: Maximum Anzahl Tags
        
    Returns:
        Liste von Tags
    """
    if not content or not content.strip():
        return []
    
    # Content auf vernünftige Länge kürzen
    preview = content[:800] if len(content) > 800 else content
    
    prompt = f"""Analysiere folgenden Text und extrahiere die 5 wichtigsten Schlagwörter/Tags.
Gib nur die Tags zurück, durch Komma getrennt, keine Erklärungen.

Text:
{preview}

Tags:"""
    
    try:
        # Generator aufrufen
        result = generator.run(prompt=prompt)
        
        # Response extrahieren (Format kann variieren)
        response = ""
        if isinstance(result, dict):
            # Haystack 2.x format
            response = result.get("replies", [""])[0]
            if not response and "response" in result:
                response = result["response"]
        elif isinstance(result, str):
            response = result
        else:
            response = str(result)
        
        # Tags parsen
        tags = []
        for tag in response.split(","):
            tag = tag.strip().lower()
            # Bereinigen: nur alphanumerisch + Bindestrich/Unterstrich
            tag = re.sub(r'[^a-z0-9_-]', '', tag.replace(' ', '-'))
            if tag and len(tag) > 2:
                tags.append(tag)
        
        return tags[:max_tags]
        
    except Exception as e:
        # Fallback: einfache Keyword-Extraktion
        print(f"Auto-Tagging fehlgeschlagen: {e}")
        return _simple_keyword_extraction(content, max_tags)


def _simple_keyword_extraction(text: str, max_tags: int = 8) -> List[str]:
    """
    Einfache Keyword-Extraktion als Fallback (ohne LLM)
    """
    # Häufige Stopwörter (vereinfacht)
    stopwords = {
        'der', 'die', 'das', 'und', 'oder', 'aber', 'für', 'von', 'mit', 
        'bei', 'zu', 'auf', 'an', 'in', 'ist', 'dem', 'den', 'des', 'ein',
        'eine', 'einer', 'eines', 'the', 'a', 'an', 'and', 'or', 'but', 'for',
        'of', 'with', 'at', 'to', 'in', 'is', 'are', 'was', 'were'
    }
    
    # Wörter extrahieren
    words = re.findall(r'\b[a-zA-ZäöüÄÖÜß]{4,}\b', text.lower())
    
    # Häufigkeit zählen
    word_freq = {}
    for word in words:
        if word not in stopwords:
            word_freq[word] = word_freq.get(word, 0) + 1
    
    # Top-N nehmen
    sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
    tags = [word for word, freq in sorted_words[:max_tags]]
    
    return tags