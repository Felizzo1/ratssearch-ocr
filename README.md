# ratssearch-ocr

OCR-Overlay für [ratssearch](https://github.com/Felizzo1/ratssearch): extrahiert Volltext aus eingescannten Dresdner Ratsdokumenten.

## Warum?

Das Mirror-Repo [offenesdresden/dresden-ratsinfo](https://github.com/offenesdresden/dresden-ratsinfo) legt für jedes PDF eine `files/{id}.txt` mit dem Volltext ab – erzeugt durch `pdftotext`. Bei eingescannten PDFs ohne eingebettete Textschicht bleibt diese Datei leer. Gemessen: ca. 7,4 % aller ~138.000 Dokumente sind betroffen.

Dieses Repo schließt diese Lücke: Es erkennt leere Texte, lädt die Original-PDFs herunter, führt OCR mit [OCRmyPDF](https://ocrmypdf.readthedocs.io/) + Tesseract durch und speichert den erkannten Text als `files/{id}.txt`.

## Was passiert hier?

```
offenesdresden/dresden-ratsinfo   (Mirror, täglich aktualisiert)
        │
        │  files/{id}.txt leer?
        ▼
ratssearch-ocr  (dieses Repo)
        │  OCR via Tesseract (Deutsch)
        │  files/{id}.txt mit extrahiertem Text
        ▼
ratssearch  (Suchindex)
        │  bevorzugt OCR-Text wenn Mirror-Text leer
        ▼
search-index.json  (durchsuchbar)
```

## Struktur

| Pfad | Beschreibung |
|---|---|
| `files/{id}.txt` | OCR-Ergebnisse, Format identisch zum Mirror |
| `state/processed.json` | Verarbeitete IDs mit Status (`ok`, `empty`, `error`) |
| `scripts/find_missing.py` | Ermittelt IDs die noch OCR benötigen |
| `scripts/ocr_batch.py` | Lädt PDFs, führt OCR durch, committet Ergebnisse |
| `.github/workflows/backfill.yml` | Manuell auslösbarer Erstlauf |
| `.github/workflows/daily.yml` | Täglicher Delta-Lauf (07:30 UTC) |

## OCR-Qualität

Die OCR-Qualität entspricht dem, was [Tesseract](https://github.com/tesseract-ocr/tesseract) aus den Scans extrahieren kann:

- **Gut**: klare Schwarz-Weiß-Scans, maschinenschriftliche Vorlagen
- **Schwächer**: stark verrauschte Scans, handschriftliche Anmerkungen, sehr kleine Schrift

Es wird ausschließlich Deutsch (`-l deu`) erkannt. Gemischte Sprachen oder Fremdwortpassagen können fehlerhaft sein.

## Backfill starten

Unter **Actions → OCR Backfill → Run workflow** mit gewünschtem `max_docs`-Wert ausführen. Pro Lauf werden bis zu N Dokumente verarbeitet und committet. Da ~10.000 leere PDFs vorhanden sind und OCR pro Dokument 5–20 Sekunden benötigt, sind mehrere Läufe nötig.

## Lizenz / Urheberrecht

Die `.txt`-Dateien in diesem Repo sind abgeleitete Daten aus öffentlichen Ratsdokumenten der Landeshauptstadt Dresden und unterliegen den jeweiligen Nutzungsbedingungen der Landeshauptstadt. Die Skripte stehen unter MIT-Lizenz.
