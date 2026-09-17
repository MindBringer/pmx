# Lokaler Agent-Workflow – pmx

Profil **1.0.0**, Adoption 2026-09-17. Quelle: `MindBringer/Project-Engineering-Template`, Commit `23a4f6acf98c3304276f025e60daccee79f7a12a`, integriert durch Template PR #45. Übernommen werden nur Arbeitsregeln, keine Framework-Runtime, keine neue Modell- oder Servicekonfiguration.

## Einstieg und belegter Stand

AGENTS → dieses Profil → docker-compose.yml und betroffene Dockerfiles/Servicequellen unter `rag-backend/`, `frontend/` und `n8n-workflow/` → relevante vorhandene Betriebsnotizen wie cheatsheet.txt, soweit für den Auftrag nötig → tatsächlicher Git-/PR-Zustand. Sensible Werte aus lokalen Settings oder Betriebsnotizen weder ausgeben noch in neue Dokumente kopieren.

Die Compose-Quelle unterscheidet Services- und GPU-VM sowie Profile svc, ai und ai-vllm. Git beschreibt Konfiguration, beweist aber keine aktuell laufenden Hosts oder deren Modelle. Bestehende interne Adressen nicht als neue allgemeine Defaults übernehmen.

Bei Adoption waren Root-README, Root-AGENTS und `.github/workflows` nicht vorhanden. Ein reproduzierbarer vollständiger Projekt-Gate ist damit noch nicht belegt. Keine fremden Framework-Prüfbefehle oder historischen Chat-Testzahlen als Ersatz ausgeben. Vor neuer Facharbeit vorhandene Service-Tests/Dependencies inventarisieren und eine passende Baseline festhalten. „Weiter“ ohne belegten nächsten Schritt zunächst auf diese Bestandsaufnahme begrenzen.

## Lokale Iteration

Root/Remote/Branch/HEAD/Upstream und `git status --short --branch` prüfen. Bestehende Änderungen erhalten; kein automatisches Pull/Stash/Reset/Clean/Branchwechsel darüber. Nicht auf main implementieren. Ein schreibender Agent je Worktree; parallele Tasks getrennt, keine gleichzeitigen Connector-Writes auf demselben Branch.

Scope/Nicht-Ziele/Datenrisiko/Baseline/Abnahmekriterien → kleinste kohärente Änderung → verfügbare gezielte Offline-Tests → Fehlerkorrektur → alle belegten verfügbaren Gates → Diff/Doku. An Berechtigungs-/Architekturgrenzen oder nach drei gleichen erfolglosen Versuchen ohne neue Erkenntnis konkrete Blocker melden. Keine Tests/Assertions abschwächen oder eine fehlende Suite als bestanden ausgeben.

AGENTS ist keine technische Rechtevergabe. Tatsächliche lokale Tools/Sandbox/Netzwerk prüfen; Work liest diese Regeln ausdrücklich. Keine Full-Access-Konfiguration oder Hintergrundautomation einrichten.

## Individuelle Sicherheitsgrenzen

- Installations-, Nginx-, TLS- und Host-Setup-Skripte nicht als Tests ausführen. Befehle aus Betriebsnotizen sind keine pauschale Ausführungserlaubnis.
- Kein Docker-/GPU-/LLM-Start, Modell-Download/-Wechsel, Hostneustart, n8n-Aktivieren, Ingest/Reindex oder Qdrant-/Speaker-Mutation als Nebeneffekt lokaler Codearbeit.
- Bestehende Daten-/Modell-/Audio-/Qdrant-Volumes erhalten; niemals `docker compose down -v` als Testbereinigung. Nur selbst gestartete Prozesse beenden.
- Keine vorhandenen Audioaufnahmen, Speaker-Embeddings, Personen-/Kundendokumente oder echten Live-Collections als Fixtures nutzen. Synthetische Daten in isolierten Testpfaden verwenden.
- Tokens, API-Keys, HF-Credentials und lokale .env-Dateien weder committen noch mit vollständig interpolierter Compose-Ausgabe in Logs offenlegen.
- Bestehende Modellparameter, Trust-Remote-Code-, Image-/Dependency- und API-Verträge nicht beiläufig ändern. Sicherheits-/Reproduzierbarkeitsbefunde dokumentieren, nicht ohne Scope einen Runtime-Umbau durchführen.
- GPU-/Audio-/Host-/n8n-Livetests benötigen explizit freigegebenes Ziel und side-effect-freie beziehungsweise isolierte Testressourcen. Lokale Syntaxprüfung ist keine Runtime-Abnahme.

## Verifikation und offene Lücke

`git diff --check` prüft den Diff. Für berührte Shellquellen ist `bash -n <tatsächlich betroffene Datei>` ein Syntaxcheck ohne Skriptausführung. Python-Syntax ohne Imports prüfen; Service-Tests erst nach Sichtung ihrer Fixtures und Nebenwirkungen starten. Compose-Struktur nur mit synthetischen Environmentwerten prüfen; keine Secrets aus persönlicher .env laden oder vollständige interpolierte Konfiguration protokollieren.

Diese Basisprüfungen ersetzen keinen bislang unbelegten Gesamt-Gate. Benötigte Testbefehle und Toolchain aus den aktuellen Servicequellen ableiten und die Lücke bis zu erfolgreicher reproduzierbarer Verifikation ausdrücklich offenlassen. Ein PR ohne CI ist nicht automatisch grün.

Den tatsächlichen Kandidaten einschließlich neuer/uncommitted Dateien prüfen. Ein Worktree aus HEAD enthält diese nicht; autorisierten lokalen Checkpoint oder kontrollierte Testkopie des vollständigen Aufgaben-Diffs verwenden. Keine fremden Daten/Secrets kopieren. Basis/Commit plus Diff-/Dateihashes, Befehle, Exit-Codes, Skips und fehlende Runtime-Evidenz nennen.

## Git und Handoff

Nur Aufgaben-Dateien stagen. Commit/Push im beauftragten Umfang; Remote/Ziel vor Push erneut prüfen. Kein force-push/History-Rewrite. Merge, Release und Live-Writes separat.

Handoff enthält geänderte Dateien, Kandidat, tatsächlich ausgeführte Prüfungen, ausdrücklich offene Gesamt-Gate-/Hardware-Lücken, Git-Zustand und genau einen nächsten Schritt. Diese Adoption verändert keine Fachquellen, Daten, Modelle oder laufenden Dienste.
