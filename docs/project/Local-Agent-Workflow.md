# Lokaler Agent-Workflow – pmx

Profil **1.2.0**, Adoption 2026-09-18. Quelle: `MindBringer/Project-Engineering-Template`, Merge `1555a15baa786f17381c5d9ecd7c2bd0c1050ca6`. Nur Arbeitsregeln; keine Framework-Runtime, Modell- oder Servicekonfiguration.

## Operatives Modell und Kontext

**Sitzungsstart:** Root/Remote/Branch/HEAD/Änderungen, `AGENTS.md` und Live-Git/PR prüfen. `readme.md`, `rag-backend/README.md`, Compose-/Docker-/Servicequellen und Betriebsnotizen nur soweit für das aktive Arbeitspaket relevant laden. Sensible lokale Werte nie in Handoff/Doku kopieren.

**Arbeitspaket:** Ziel, Nicht-Ziele, Daten-/Runtime-Risiko, betroffene Services/Verträge, relevante Quellen, gezielte Offline-Prüfungen und DoD festlegen. Genau ein primäres nächstes Paket.

**Reparaturschleife:** kleinste kohärente Änderung → gezielte Offline-Prüfung → Fehleranalyse/Korrektur. Kein vollständiger Neueinstieg nach jedem Edit.

**Abschluss-Gate:** tatsächlichen Kandidaten einschließlich neuer Dateien mit allen belegten verfügbaren Gates prüfen; fehlende Runtime-/GPU-/Host-Evidenz ausdrücklich offenlassen.

## Semantisches Model Routing

```text
fast               → mechanische, klar lokalisierte, risikoarme Änderung
standard-reasoning → normale Python-/Frontend-/Compose-/Workflow-/Testarbeit
deep-reasoning     → mehrere gekoppelte Services, RAG/LLM/Audio/Agent-Orchestrierung,
                     Architektur, komplexe Root-Cause oder hoher Änderungsradius
```

Signale: `complexity`, `ambiguity`, `blastRadius`, `crossSubsystem`, `novelty`, `dataRisk`, `failedAttempts`. Nach zwei gleichartigen erfolglosen Reparaturen oder größer erkanntem Scope Reasoning/Klasse eskalieren; nach drei ohne Erkenntnis Blocker. Ein stärkeres Modell ersetzt keine GPU-/Host-/Datenfreigabe.

Codex/lokal für Repo-Implementierung und Offline-Tests; Work für systemübergreifende Recherche/Artefakte; Chat für Scope-/Architektur-/Freigabeentscheidungen.

## Sicherheits- und Runtime-Grenzen

- Installations-, Nginx-, TLS- und Host-Setup-Skripte nicht als Tests ausführen.
- Kein Docker-/GPU-/LLM-Start, Modell-Download/-Wechsel, Hostneustart, n8n-Aktivieren, Ingest/Reindex oder Qdrant-/Speaker-Mutation als Nebeneffekt.
- Daten-/Modell-/Audio-/Qdrant-Volumes erhalten; niemals `docker compose down -v` als Testbereinigung.
- Keine echten Audioaufnahmen, Speaker-Embeddings, Personen-/Kundendokumente oder Live-Collections als Fixtures.
- Tokens/API-Keys/HF-Credentials/`.env` weder committen noch in vollständig interpolierten Compose-Logs offenlegen.
- Modellparameter, Trust-Remote-Code-, Image-/Dependency- und API-Verträge nicht beiläufig ändern.
- GPU-/Audio-/Host-/n8n-Livetests benötigen separat freigegebenes Ziel und isolierte Ressourcen.

## Testökonomie

Aktuell existiert kein belegter vollständiger CI-/Gesamt-Gate. Während Reparaturen: `git diff --check`, Syntax-/Parsing-Prüfungen nur für betroffene Quellen und weitere Tests erst nach Sichtung ihrer Fixtures/Nebenwirkungen. Python-Syntax ohne Imports; Shell mit `bash -n`; JavaScript Syntaxcheck; n8n-JSON parsen. Compose nur mit synthetischen Environmentwerten prüfen und keine Secrets aus persönlicher `.env` laden.

Die bereits dokumentierte Offline-Baseline (17 Python-, 9 Shell-, 4 JavaScript-Dateien, 6 n8n-Workflows auf dem damaligen Adoptionsstand) bleibt historische Baseline, nicht Verifikation neuer Änderungen. Ein PR ohne CI ist nicht automatisch grün.

Nächster technischer Fachschritt bleibt: isolierte synthetische Service-Testbaseline ohne Modell-Downloads oder Live-Collections entwerfen und ausführen, bevor neue Fachlogik entwickelt wird.

## Git und Handoff

Bestehende Änderungen erhalten; ein schreibender Agent je Worktree. Nur Aufgaben-Dateien stagen; Commit/Push im beauftragten Umfang, kein Force-Push. Merge/Release/Runtime-Writes separat.

Handoff enthält Kandidat, Dateien, tatsächlich ausgeführte Prüfungen, offene Gesamt-Gate-/Hardware-Lücken, Git-Zustand und genau ein primäres nächstes Arbeitspaket. Bereits erfolgreich ausgeführte Befehle bei lokalem Agenten nicht pauschal wiederholen.
