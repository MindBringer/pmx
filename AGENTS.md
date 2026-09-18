# Agent Instructions – pmx

<!-- local-agent-workflow: 1.2.0 -->
Vor Implementierung bei neuer Profilversion `docs/project/Local-Agent-Workflow.md` lesen. Danach nur die für das aktive Arbeitspaket relevanten Compose-/Docker-/Servicequellen und Betriebsnotizen laden.

## Arbeitsvertrag

- Sitzungsstart → Arbeitspaket → Reparaturschleife → Abschluss-Gate → Handoff.
- Tatsächlichen Repo-/Remote-/Branch-/Git-Zustand und verfügbare Werkzeuge prüfen. Chat ist keine Source of Truth.
- Bestehende Änderungen erhalten; kein automatisches Pull/Stash/Reset/Clean/Branchwechsel. Nicht auf `main` implementieren. Ein schreibender Agent je Worktree.
- Pro Arbeitspaket die kleinste voraussichtlich ausreichende Modellklasse `fast`, `standard-reasoning` oder `deep-reasoning` wählen; konkrete Modellnamen nicht persistieren. Erst anhand belegter Komplexität/Fehlschläge eskalieren.
- Während Reparaturen kleinste aussagekräftige Offline-Tests; fehlenden Gesamt-Gate nicht vortäuschen. Tatsächlichen Kandidaten einschließlich neuer Dateien prüfen.
- Commit/Push im beauftragten Umfang; Merge/Release/Live-Writes separat. Kein Force-Push/History-Rewrite.

## pmx-Grenzen

Keine Installations-/Nginx-/TLS-/Hostskripte als Tests ausführen. Keine automatischen GPU-/LLM-/Docker-Starts, Modellwechsel/-Downloads, n8n-Aktivierungen, Ingest/Reindex- oder Qdrant-/Speaker-Writes. Daten- und Modellvolumes erhalten; kein `down -v`, keine globale Prozessbereinigung.

Nur synthetische/isolierte Fixtures. Vorhandene Audioaufnahmen, Speaker-Embeddings, echte Dokumente und Live-Collections nicht als Agent-Testdaten verwenden. Keine lokalen `.env`-Dateien/Tokens/API-Keys/Hostcredentials committen oder als interpolierte Compose-Ausgabe protokollieren.

Bei Adoption ist weiterhin kein vollständiger reproduzierbarer Gesamt-Gate belegt. Verfügbare Syntax-/Diff-Prüfungen sind keine Runtime-Abnahme. Neue Facharbeit benötigt zunächst eine belegte Testbaseline.

AGENTS erteilt keine technischen Rechte. Work/Codex lesen diese Regeln ausdrücklich; keine Full-Access-Konfiguration oder Hintergrundautomation einrichten.

Handoff: Kandidat, Dateien, tatsächliche Befehle/Exit-Codes/Skips, offene Gesamt-Gate-/Hardware-Lücken, Git-Zustand und genau ein primäres nächstes Arbeitspaket.
<!-- /local-agent-workflow -->
