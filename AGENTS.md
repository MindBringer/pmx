# Agent Instructions – pmx

<!-- local-agent-workflow: 1.0.0 -->
Vor Implementierung `docs/project/Local-Agent-Workflow.md` vollständig lesen, danach Compose-/Docker-/Servicequellen und die im Profil genannten vorhandenen Betriebsnotizen. Technische Notizen nicht als pauschalen Ausführungsauftrag behandeln.

## Arbeitsvertrag

- Tatsächlichen Repo-/Remote-/Branch-/Git-Zustand und verfügbare Werkzeuge prüfen. „Weiter“ ohne belegten nächsten Schritt zunächst auf sichere Bestandsaufnahme begrenzen.
- Lokal-first im beauftragten Scope: Baseline → kleinste Änderung → verfügbare Offline-Tests → Fehlerkorrektur → Diff/Doku/Handoff. Kein automatischer Runtime-Umbau.
- Bestehende Änderungen erhalten, kein automatisches Pull/Stash/Reset/Clean/Branchwechsel darüber. Nicht auf main implementieren. Ein schreibender Agent je Worktree; keine gleichzeitigen Connector-Writes auf demselben Branch.
- Tatsächlichen Kandidaten einschließlich neuer/uncommitted Dateien testen, nicht unbemerkt alten HEAD. Fehlende Tests/Gesamt-Gates und Hardware-Evidenz ausdrücklich als offen kennzeichnen.
- Commit/Push im beauftragten Umfang; Merge/Release/Live-Writes separat. Kein force-push/History-Rewrite, nur Aufgaben-Dateien stagen.

## pmx-Grenzen

Keine Installations-/Nginx-/TLS-/Hostskripte als Tests ausführen. Keine automatischen GPU-/LLM-/Docker-Starts, Modellwechsel, Downloads, n8n-Aktivierungen, Ingest/Reindex- oder Qdrant-/Speaker-Writes. Daten- und Modellvolumes erhalten; kein `down -v`, keine globale Prozessbereinigung.

Nur synthetische/isolierte Fixtures. Vorhandene Audioaufnahmen, Speaker-Embeddings, echte Dokumente und Live-Collections nicht als Agent-Testdaten verwenden. Keine lokalen .env-Dateien/Tokens/API-Keys/Hostcredentials committen oder als interpolierte Compose-Ausgabe protokollieren.

Bei Adoption ist kein GitHub-Actions-Workflow und kein vollständiger reproduzierbarer Gesamt-Gate belegt. Verfügbare Syntax-/Diff-Prüfungen sind keine Runtime-Abnahme; fehlende Gates nicht durch alte Chatwerte oder fremde Frameworkbefehle vortäuschen. Neue Facharbeit benötigt zunächst eine belegte Testbaseline.

AGENTS erteilt keine technischen Rechte. Work liest die Regeln ausdrücklich; keine Full-Access-Konfiguration oder Hintergrundautomation einrichten. Dieses Profil installiert keine Framework-Runtime und verändert keine Dienste oder Modelle.

Handoff: Kandidat, Dateien, tatsächliche Befehle/Exit-Codes/Skips, offene Gesamt-Gate-/Hardware-Lücken, Git-Zustand und genau ein nächster Schritt.
<!-- /local-agent-workflow -->
