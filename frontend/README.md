# Frontend Split

Diese Zip enthält die aufgeteilte Fassung deines Frontends:

- **index.html** – Markup, bindet `styles.css` und `app.js` ein (per `<link>` / `defer`).
- **styles.css** – Aus dem `<style>`-Block extrahiert.
- **app.js** – Aus dem inline-`<script>` extrahiert.

## Hinweise

- Skript wird per `defer` geladen, d. h. DOM ist beim Start verfügbar (entspricht Inline-Variante am Body-Ende).
- Ressourcen liegen auf derselben Ebene wie `index.html`. Wenn du einen anderen Pfad möchtest (z. B. `/assets/`), einfach die Referenzen in `index.html` anpassen.
- Bei CSP- oder Caching-Anforderungen kannst du später eine Hash-Versionierung ergänzen (z. B. `app.2025-08-22.js`).

Viel Erfolg!
